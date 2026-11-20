"""Run an isolated real browser/API/parser/local-Agent/model acceptance test."""
import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.agent_bridge.contracts import DispatchManifest
from app.agent_bridge.transport import create_transport
from app.auth.security import hash_password
from app.config import Settings
from app.db.models import AgentRun, User

ROOT = Path(__file__).resolve().parents[2]


def pdf_fixture():
    lines = [
        'Integration acceptance fixture - synthetic test material, not a published paper.',
        'Purpose: verify the complete browser, backend, PDF parser and Agent data flow.',
        'The backend saves every uploaded PDF in persistent storage before acknowledging it.',
        'The database records the file identifier, title, size and SHA-256 content digest.',
        'An independent parser extracts text and records the number of physical PDF pages.',
        'The backend packages the selected original PDF for the local Agent process.',
        'The Agent checks the file content digest before reading the supplied document.',
        'A research answer should cite verbatim evidence from the original PDF page.',
        'The reader opens the cited physical page without leaving the current browser tab.',
        'Returning from the reader restores the research task and selected evidence.',
        'Idempotent submission retries return the same task rather than executing it twice.',
        'This fixture describes acceptance expectations; it is not an empirical research study.',
    ]
    stream = ('BT /F1 10 Tf 45 780 Td 18 TL ' + ' '.join(
        '(' + line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ') Tj T*' for line in lines) + ' ET').encode('ascii')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    data, offsets = b'%PDF-1.4\n', [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(data))
        data += str(index).encode() + b' 0 obj\n' + value + b'\nendobj\n'
    start = len(data)
    data += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def wait_ready(url, processes):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError('A test service exited; inspect this run\'s component logs')
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError('A test service did not become ready')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-model-requests', action='store_true', help='Acknowledge that this test invokes the configured real model')
    parser.add_argument('--browser-python', type=Path, default=ROOT / ('runtime/browser-venv/Scripts/python.exe' if os.name == 'nt' else 'runtime/browser-venv/bin/python'))
    arguments = parser.parse_args()
    if not arguments.allow_model_requests:
        parser.error('--allow-model-requests is required; a small real model execution may incur charges')
    if not arguments.browser_python.is_file() or not shutil.which('node'):
        parser.error('Prepare the browser Python environment and Node.js first')
    settings = Settings()
    base = make_url(settings.database_url.get_secret_value())
    if base.host not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('This harness only creates isolated databases on local PostgreSQL')
    transport = create_transport(settings.model_copy(update={'agent_transport': 'local'}))
    run_id = uuid4().hex
    database = 'agent_e2e_tests_' + run_id
    assert re.fullmatch(r'agent_e2e_tests_[0-9a-f]{32}', database)
    logs = ROOT / 'runtime/live-integration' / run_id
    logs.mkdir(parents=True)
    admin = create_engine(base.set(database='postgres'), isolation_level='AUTOCOMMIT', connect_args={'connect_timeout': 5})
    engine = None
    created = False
    processes = []
    with ExitStack() as resources:
        try:
            with admin.connect() as connection:
                connection.exec_driver_sql('CREATE DATABASE "' + database + '"')
            created = True
            engine = create_engine(base.set(database=database), connect_args={'connect_timeout': 5})
            migration = Config(str(ROOT / 'backend/alembic.ini'))
            with engine.connect() as connection:
                migration.attributes['connection'] = connection
                command.upgrade(migration, 'head')
                command.check(migration)
            password = secrets.token_urlsafe(24)
            sessions = sessionmaker(engine)
            with sessions.begin() as session:
                session.add(User(id=uuid4(), username='e2e_' + run_id[:12], username_key='e2e_' + run_id[:12],
                    email='e2e_' + run_id + '@example.org', email_key='e2e_' + run_id + '@example.org',
                    password_hash=hash_password(password), status='active', email_verified_at=datetime.now(timezone.utc)))
            work = Path(resources.enter_context(tempfile.TemporaryDirectory(prefix='work-', dir=logs)))
            sockets = [socket.socket(), socket.socket()]
            for listener in sockets:
                listener.bind(('127.0.0.1', 0))
            api_port, frontend_port = [listener.getsockname()[1] for listener in sockets]
            for listener in sockets:
                listener.close()
            api = f'http://127.0.0.1:{api_port}'
            frontend = f'http://127.0.0.1:{frontend_port}'
            environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8',
                'DATABASE_URL': base.set(database=database).render_as_string(hide_password=False),
                'STORAGE_ROOT': str(work / 'storage'), 'AGENT_EXCHANGE_ROOT': str(work / 'exchange'),
                'TASK_RUNNER': 'agent', 'AGENT_DISPATCH_ENABLED': 'true', 'AGENT_TRANSPORT': 'local',
                'AGENT_LOCAL_ROOT': str(transport.agent_root), 'AGENT_LOCAL_PYTHON': str(transport.python),
                'AGENT_TIMEOUT_SECONDS': '360', 'AGENT_SEARCH_MAX_PAPERS': '1', 'AGENT_CONTEXT_TOKENS': '32000',
                'AGENT_MAX_STEPS': '24', 'FRONTEND_PUBLIC_URL': frontend, 'AUTH_COOKIE_SECURE': 'false',
                'AUTH_RATE_KEY': secrets.token_urlsafe(32), 'AUTH_CSRF_KEY': secrets.token_urlsafe(32),
                'CORS_ORIGINS': json.dumps([frontend]), 'ARXIV_ENABLED': 'false',
                'API_PROXY_TARGET': api, 'VITE_API_BASE_URL': ''}
            live_settings = Settings(_env_file=None, **{name.lower(): value for name, value in environment.items()
                if name in ('DATABASE_URL', 'STORAGE_ROOT', 'AGENT_EXCHANGE_ROOT', 'AGENT_LOCAL_ROOT', 'AGENT_LOCAL_PYTHON')},
                task_runner='agent', agent_dispatch_enabled=True, agent_transport='local')
            commands = [
                ('api', [sys.executable, '-B', '-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', str(api_port)], ROOT / 'backend'),
                ('parser', [sys.executable, '-B', '-m', 'app.parser_worker'], ROOT / 'backend'),
                ('agent-worker', [sys.executable, '-B', '-m', 'app.runner_worker'], ROOT / 'backend'),
                ('vite', [shutil.which('node'), str(ROOT / 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', str(frontend_port), '--strictPort'], ROOT / 'frontend'),
            ]
            for name, invocation, directory in commands:
                output = resources.enter_context((logs / (name + '.log')).open('w', encoding='utf-8'))
                processes.append(subprocess.Popen(invocation, cwd=directory, env=environment, stdout=output,
                    stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
            wait_ready(api + '/ready', processes)
            wait_ready(frontend, processes)
            fixture = work / 'Integration-Acceptance-Fixture.pdf'
            fixture.write_bytes(pdf_fixture())
            browser_environment = {**environment, 'LIVE_RESEARCH_URL': frontend,
                'LIVE_RESEARCH_USER': 'e2e_' + run_id[:12], 'LIVE_RESEARCH_PASSWORD': password,
                'LIVE_RESEARCH_PDF': str(fixture), 'LIVE_RESEARCH_OUTPUT': str(logs / 'result.json')}
            if (ROOT / 'runtime/pw-browsers').is_dir():
                browser_environment.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / 'runtime/pw-browsers'))
            print('Starting real acceptance with an isolated database; report: ' + str(logs), flush=True)
            result = subprocess.run([str(arguments.browser_python.resolve()), '-B', str(ROOT / 'frontend/checks/live-research.py')],
                cwd=ROOT, env=browser_environment, timeout=600)
            return result.returncode
        finally:
            if engine is not None and 'live_settings' in locals():
                try:
                    from sqlalchemy import select
                    local = create_transport(live_settings)
                    with sessionmaker(engine)() as session:
                        runs = [(DispatchManifest.model_validate(run.manifest), run.remote_job_id) for run in session.scalars(select(AgentRun))]
                    for manifest, job_id in runs:
                        deadline = time.monotonic() + 10
                        while not local.cancel(manifest, job_id) and time.monotonic() < deadline:
                            time.sleep(0.2)
                except Exception as error:
                    print('Local job cleanup requires inspection: ' + type(error).__name__, flush=True)
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
            if engine is not None:
                engine.dispose()
            try:
                if created:
                    with admin.connect() as connection:
                        connection.exec_driver_sql('DROP DATABASE "' + database + '" WITH (FORCE)')
                    print('CLEANUP PASSED: isolated database dropped; existing data preserved.', flush=True)
            finally:
                admin.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
