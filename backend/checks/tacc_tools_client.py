"""Standard-library CPU smoke client; private config and response bodies stay local."""
import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_PDF = 20 * 1024 * 1024


class ClientFailure(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Deny even same-host redirects: no credential-bearing request is replayed.
        return None


class Client:
    def __init__(self, config):
        self.config = config
        url = urllib.parse.urlsplit(config['base_url'])
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.path not in ('', '/') or url.query or url.fragment):
            raise ClientFailure('invalid_config')
        for key in ('cookie', 'csrf_token', 'origin', 'query'):
            value = config[key]
            if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
                raise ClientFailure('invalid_config')
        if any(c in config['cookie'] for c in ';, '):
            raise ClientFailure('invalid_config')
        self.base = config['base_url'].rstrip('/')
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, *, authenticated=True, payload=None, timeout=20, max_bytes=None):
        if not path.startswith('/') or path.startswith('//'):
            raise ClientFailure('invalid_path')
        headers = {'Accept': 'application/json'}
        if authenticated:
            headers['Cookie'] = 'lra_dev_session=' + self.config['cookie']
        if payload is not None:
            headers.update({'Origin': self.config['origin'], 'X-CSRF-Token': self.config['csrf_token'],
                            'Content-Type': 'application/json'})
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None)
        try:
            response = self.opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            limit = max_bytes if max_bytes is not None else 1024 * 1024
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ClientFailure('response_too_large')
            return response.status, body


def run(config, *, poll_timeout=150, poll_interval=2):
    started = time.monotonic()
    report = {'ok': False, 'status_codes': {}}

    def checked(label, method, path, expected=(200,), **kwargs):
        status, body = client.request(method, path, **kwargs)
        report['status_codes'].setdefault(label, []).append(status)
        if status not in expected:
            try:
                code = json.loads(body).get('error', {}).get('code')
                if isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', code):
                    report['backend_error_code'] = code
            except (ValueError, AttributeError):
                pass
            raise ClientFailure('unexpected_http_status')
        return body

    try:
        client = Client(config)
        checked('health', 'GET', '/health', authenticated=False)
        search_path = '/api/v1/paper-search?' + urllib.parse.urlencode({'q': config['query'], 'limit': 3})
        checked('anonymous_search', 'GET', search_path, expected=(401,), authenticated=False)
        items = json.loads(checked('search', 'GET', search_path))['items']
        versioned = re.compile(r'(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})v\d+')
        candidates = [item for item in items if versioned.fullmatch(item.get('external_id', ''))]
        requested = config.get('external_id')
        chosen = next((item for item in candidates if requested is None or item['external_id'] == requested), None)
        if chosen is None:
            raise ClientFailure('selection_not_returned')
        report['search_results'] = [{'external_id': i['external_id'], 'title': i['title']} for i in candidates]
        report['selected_external_id'] = chosen['external_id']
        job = json.loads(checked('import', 'POST', '/api/v1/paper-imports', expected=(200, 202),
                                 payload={'provider': 'arxiv', 'external_id': chosen['external_id']}))
        deadline = time.monotonic() + min(150, max(0, poll_timeout))
        job_path = '/api/v1/paper-imports/' + urllib.parse.quote(str(job['id']), safe='')
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ClientFailure('import_timeout')
            job = json.loads(checked('poll', 'GET', job_path, timeout=min(20, remaining)))
            if job['status'] == 'succeeded':
                break
            if job['status'] == 'failed':
                code = (job.get('error') or {}).get('code')
                if isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', code):
                    report['backend_error_code'] = code
                raise ClientFailure('import_failed')
            if job['status'] not in ('queued', 'running'):
                raise ClientFailure('invalid_response')
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        paper = urllib.parse.quote(str(job['paper_id']), safe='')
        pdf = checked('pdf', 'GET', '/api/v1/papers/' + paper + '/file', max_bytes=MAX_PDF)
        if not pdf.startswith(b'%PDF-'):
            raise ClientFailure('invalid_pdf')
        report['pdf'] = {'size_bytes': len(pdf), 'sha256': hashlib.sha256(pdf).hexdigest()}
        report['ok'] = True
    except ClientFailure as exc:
        report['error'] = str(exc)
    except (KeyError, TypeError, ValueError, AttributeError):
        report['error'] = 'invalid_config_or_response'
    except Exception:
        # Network and parser exception messages may include secrets or response bodies.
        report['error'] = 'request_failed'
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        with open(args.config, encoding='utf-8') as source:
            config = json.load(source)
        result = run(config)
    except Exception:
        result = {'ok': False, 'error': 'config_read_failed'}
    try:
        with open(args.output, 'w', encoding='utf-8') as target:
            json.dump(result, target, indent=2)
            target.write('\n')
    except Exception:
        print('Could not write result file.')
        return 1
    print('Tool check succeeded.' if result['ok'] else 'Tool check failed; see sanitized result file.')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
