"""Run the current offline frontend checks with an optional existing Vite URL."""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import playwright

ROOT = Path(__file__).resolve().parents[2]
CHECKS = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Reuse an existing local Vite server instead of starting one')
    parser.add_argument('--only', action='append', help='Run one or more check filenames')
    arguments = parser.parse_args()
    scripts = sorted([*CHECKS.glob('*.mjs'), *CHECKS.glob('*-browser.py'), *CHECKS.glob('*-browser.cjs')])
    if arguments.only:
        names = {script.name for script in scripts}
        if set(arguments.only) - names:
            parser.error('Unknown check: ' + ', '.join(sorted(set(arguments.only) - names)))
        scripts = [script for script in scripts if script.name in arguments.only]
    node = shutil.which('node')
    if not node:
        parser.error('Node.js is required')
    logs = ROOT / 'runtime/frontend-checks'
    logs.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    environment.setdefault('PLAYWRIGHT_MODULE', str(Path(playwright.__file__).parent / 'driver/package'))
    browsers = ROOT / 'runtime/pw-browsers'
    if browsers.is_dir():
        environment.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(browsers))
    server = None
    results = []
    with (logs / 'vite.log').open('w', encoding='utf-8') as server_log:
        try:
            base = arguments.url
            if not base:
                with socket.socket() as listener:
                    listener.bind(('127.0.0.1', 0))
                    port = listener.getsockname()[1]
                base = f'http://127.0.0.1:{port}'
                server = subprocess.Popen([node, str(ROOT / 'frontend/node_modules/vite/bin/vite.js'),
                    '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=ROOT / 'frontend',
                    env=environment, stdout=server_log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            base = base.rstrip('/')
            for attempt in range(60):
                try:
                    with urlopen(base, timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    if server and server.poll() is not None:
                        raise RuntimeError('Vite exited; see ' + str(logs / 'vite.log')) from None
                    time.sleep(0.25)
            else:
                raise RuntimeError('Vite did not become ready: ' + base)
            for name in ('AGENT_PREVIEW_URL', 'AGENT_WORKSPACE_URL', 'SEARCH_PREVIEW_URL', 'LIBRARY_PREVIEW_URL', 'SIDEBAR_PREVIEW_URL'):
                environment[name] = base
            for script in scripts:
                command = [sys.executable, '-B'] if script.suffix == '.py' else [node]
                destination = logs / (script.name + '.log')
                with destination.open('w', encoding='utf-8') as output:
                    try:
                        result = subprocess.run([*command, str(script)], cwd=ROOT, env=environment,
                            stdout=output, stderr=subprocess.STDOUT, timeout=180)
                        passed = result.returncode == 0
                    except subprocess.TimeoutExpired:
                        passed = False
                        output.write('\nTIMEOUT: exceeded 180 seconds\n')
                results.append(dict(check=script.name, passed=passed))
                print(('PASS ' if passed else 'FAIL ') + script.name, flush=True)
                if not passed:
                    print('\n'.join(destination.read_text(encoding='utf-8').splitlines()[-30:]), flush=True)
        finally:
            if server:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)
    (logs / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f'{sum(result["passed"] for result in results)}/{len(results)} checks passed; APIs are mocked.', flush=True)
    return 0 if results and all(result['passed'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
