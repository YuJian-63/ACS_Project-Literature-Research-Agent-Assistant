import hashlib
import importlib.util
import io
import json
from pathlib import Path
import urllib.error
import urllib.request

import pytest

PATH = Path(__file__).parents[1] / 'checks' / 'tacc_tools_client.py'


def module():
    assert PATH.exists(), 'CPU tools client must exist'
    spec = importlib.util.spec_from_file_location('tacc_client', PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def config(**kwargs):
    return dict(base_url='https://tunnel.example', cookie='SECRET', csrf_token='CSRFSECRET',
                origin='http://127.0.0.1:5173', query='attention is all you need', **kwargs)


def responses(pdf=b'%PDF-1.7\nexample', imported=None):
    return [(200, b'{}'), (401, b'{}'), (200, json.dumps({'items': [
        {'external_id': '1706.03762v7', 'title': 'Attention Is All You Need', 'authors': ['private']}
    ]}).encode()), (202, json.dumps(imported or {'id': 'job', 'status': 'queued'}).encode()),
            (200, b'{"status":"succeeded","paper_id":"paper"}'), (200, pdf)]


def run_fake(mod, monkeypatch, seq, cfg=None):
    calls = []
    def request(self, method, path, *, authenticated=True, payload=None, timeout=20, max_bytes=None):
        calls.append((method, path, authenticated, payload))
        status, body = seq.pop(0)
        if max_bytes is not None and len(body) > max_bytes:
            raise mod.ClientFailure('response_too_large')
        return status, body
    monkeypatch.setattr(mod.Client, 'request', request)
    return mod.run(cfg or config()), calls


def test_complete_workflow_and_sanitized_report(monkeypatch):
    mod = module()
    result, calls = run_fake(mod, monkeypatch, responses())
    assert result['ok'] is True
    assert result['selected_external_id'] == '1706.03762v7'
    assert result['pdf']['sha256'] == hashlib.sha256(b'%PDF-1.7\nexample').hexdigest()
    assert calls[1][2] is False
    assert calls[3][3] == {'provider': 'arxiv', 'external_id': '1706.03762v7'}
    assert 'private' not in json.dumps(result)
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('url', ['http://tunnel.example', 'https://user:pw@tunnel.example', 'https://tunnel.example/path', 'https://tunnel.example?secret=x'])
def test_invalid_endpoint(url):
    mod = module()
    cfg = config(); cfg['base_url'] = url
    assert mod.run(cfg)['error'] == 'invalid_config'


@pytest.mark.parametrize('pdf', [b'not a pdf', b'%PDF-' + b'x' * (20 * 1024 * 1024)])
def test_invalid_pdf(monkeypatch, pdf):
    mod = module()
    result, _ = run_fake(mod, monkeypatch, responses(pdf))
    assert result['ok'] is False


def test_unreturned_selection_rejected(monkeypatch):
    mod = module()
    result, calls = run_fake(mod, monkeypatch, responses(), config(external_id='1234.5678v1'))
    assert result['error'] == 'selection_not_returned'
    assert len(calls) == 3


def test_backend_error_only_code(monkeypatch):
    mod = module()
    result, _ = run_fake(mod, monkeypatch, [(503, b'{"error":{"code":"UNAVAILABLE","message":"SECRET"}}')])
    assert result['backend_error_code'] == 'UNAVAILABLE'
    assert 'SECRET' not in json.dumps(result)


def test_redirects_never_followed():
    mod = module()
    handler = mod.NoRedirect()
    req = urllib.request.Request('https://tunnel.example', headers={'Cookie': 'SECRET'})
    assert handler.redirect_request(req, None, 302, 'Found', {}, 'https://evil.example') is None


def test_request_sets_credentials_only_when_authenticated(monkeypatch):
    mod = module()
    seen = []
    class Response(io.BytesIO):
        status = 200
    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            return Response(b'{}')
    monkeypatch.setattr(mod.urllib.request, 'build_opener', lambda *args: Opener())
    client = mod.Client(config())
    client.request('GET', '/health', authenticated=False)
    client.request('POST', '/api/v1/paper-imports', payload={})
    assert seen[0].get_header('Cookie') is None
    assert seen[1].get_header('Cookie') == 'lra_dev_session=SECRET'
    assert seen[1].get_header('X-csrf-token') == 'CSRFSECRET'
    assert seen[1].get_header('Origin') == 'http://127.0.0.1:5173'


def test_poll_deadline_without_network(monkeypatch):
    mod = module()
    seq = responses()
    def request(*args, **kwargs):
        return seq.pop(0)
    monkeypatch.setattr(mod.Client, 'request', request)
    result = mod.run(config(), poll_timeout=0)
    assert result['error'] == 'import_timeout'


def test_raw_network_error_redacted(monkeypatch):
    mod = module()
    def request(*args, **kwargs):
        raise RuntimeError('SECRET response body')
    monkeypatch.setattr(mod.Client, 'request', request)
    result = mod.run(config())
    assert result['error'] == 'request_failed'
    assert 'SECRET' not in json.dumps(result)


def test_cli_invalid_config_sanitized(monkeypatch, tmp_path, capsys):
    mod = module()
    private = tmp_path / 'private.json'
    output = tmp_path / 'result.json'
    private.write_text('SECRET invalid JSON')
    monkeypatch.setattr('sys.argv', ['client', '--config', str(private), '--output', str(output)])
    assert mod.main() == 1
    assert json.loads(output.read_text()) == {'ok': False, 'error': 'config_read_failed'}
    assert 'SECRET' not in capsys.readouterr().out
