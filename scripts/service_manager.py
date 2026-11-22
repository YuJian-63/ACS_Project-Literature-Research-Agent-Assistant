"""Initialize and supervise a local development stack on Windows, Linux and macOS."""

import argparse
from contextlib import contextmanager
from io import StringIO
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, build_opener

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.auth.security import check_config
from app.config import Settings


ROOT = Path(__file__).resolve().parents[1]
WEB_URL = "http://127.0.0.1:5173"
SECRET_KEYS = ("AUTH_RATE_KEY", "AUTH_CSRF_KEY", "MAIL_OUTBOX_KEY")
urlopen = build_opener(ProxyHandler({})).open


class ServiceError(Exception):
    pass


def prepare_configuration(root):
    path = root / "backend/.env"
    if path.is_symlink():
        raise ServiceError("backend/.env is a symlink; initialize its configuration manually.")
    fresh = not path.exists()
    source = root / "backend/.env.example" if fresh else path
    original = source.read_text(encoding="utf-8")
    values = dotenv_values(stream=StringIO(original), interpolate=False)
    updates = {}
    if fresh:
        updates.update(
            FRONTEND_PUBLIC_URL=WEB_URL,
            CORS_ORIGINS=json.dumps([WEB_URL]),
            AUTH_COOKIE_SECURE="false",
            AGENT_DISPATCH_ENABLED="false",
            ARXIV_ENABLED="false",
            EVALUATION_ENABLED="false",
        )
    for key in SECRET_KEYS:
        if not values.get(key):
            updates[key] = (Fernet.generate_key().decode() if key == "MAIL_OUTBOX_KEY"
                            else secrets.token_urlsafe(32))
    if not updates:
        return
    descriptor, name = tempfile.mkstemp(prefix=".service-env-", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(original)
        for key, value in updates.items():
            set_key(str(staged), key, value)
        staged.chmod(0o600)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def read_settings(root):
    path = root / "backend/.env"
    if not path.is_file():
        raise ServiceError("backend/.env is missing. Run init first.")
    return Settings(_env_file=path)


def validate_configuration(settings):
    if (settings.frontend_public_url != WEB_URL or settings.auth_cookie_secure
            or WEB_URL not in settings.cors_origins):
        raise ServiceError("Local launch requires FRONTEND_PUBLIC_URL=http://127.0.0.1:5173, "
                           "AUTH_COOKIE_SECURE=false and matching CORS_ORIGINS. "
                           "Use systemd for an existing HTTPS ECS deployment.")
    try:
        check_config(settings)
    except Exception:
        raise ServiceError("Invalid AUTH_RATE_KEY / AUTH_CSRF_KEY; run init or check backend/.env.") from None
    if any((settings.smtp_username, settings.smtp_from,
            settings.smtp_auth_code and settings.smtp_auth_code.get_secret_value())):
        try:
            check_config(settings, mail=True)
        except Exception:
            raise ServiceError("Complete SMTP_HOST/PORT/USERNAME/FROM/AUTH_CODE and MAIL_OUTBOX_KEY "
                               "in backend/.env before starting Mail.") from None
    if settings.arxiv_enabled and not settings.arxiv_configured:
        raise ServiceError("ARXIV_ENABLED requires ARXIV_CONTACT_EMAIL.")
    if settings.evaluation_enabled and not settings.evaluation_configured:
        raise ServiceError("EVALUATION_ENABLED requires EVALUATION_MODEL and EVALUATION_API_KEY.")


def validate_database(root, settings):
    values = {**dotenv_values(root / "backend/.env"), **os.environ}
    database = make_url(settings.database_url.get_secret_value())
    try:
        valid = (database.host in {"127.0.0.1", "localhost"}
                 and database.port == int(values.get("POSTGRES_PORT", "5432"))
                 and database.database == values.get("POSTGRES_DB", "literature")
                 and database.username == values.get("POSTGRES_USER", "literature")
                 and database.password == values.get("POSTGRES_PASSWORD"))
    except ValueError:
        valid = False
    if not valid:
        raise ServiceError("DATABASE_URL must match POSTGRES_DB/USER/PASSWORD/PORT for Compose. "
                           "For an existing database, use init --external-db. "
                           "Changing .env does not change credentials inside an existing volume.")


def npm_command():
    return "npm.cmd" if os.name == "nt" else "npm"


def run_command(command, cwd):
    subprocess.run(command, cwd=cwd, check=True)


def require_tools(*, docker=False):
    for name in ("node", npm_command()) + (("docker",) if docker else ()):
        if not shutil.which(name):
            raise ServiceError(f"Missing {name}; install it and reopen the terminal.")
    result = subprocess.run(["node", "--version"], check=True, capture_output=True, text=True)
    version = tuple(int(part) for part in result.stdout.strip().lstrip("v").split("."))
    if not ((20, 19, 0) <= version < (21, 0, 0) or version >= (22, 12, 0)):
        raise ServiceError("Node.js must satisfy ^20.19.0 || >=22.12.0 (frontend/package.json).")
    if docker:
        subprocess.run(["docker", "compose", "version"], check=True, stdout=subprocess.DEVNULL)


def worker_modules(settings):
    workers = [("parser", "app.parser_worker")]
    if settings.smtp_configured:
        workers.append(("mail", "app.mail_worker"))
    if settings.agent_dispatch_enabled:
        workers.append(("runner", "app.runner_worker"))
    if settings.arxiv_configured:
        workers.append(("imports", "app.import_worker"))
    if settings.evaluation_configured:
        workers.append(("evaluation", "app.evaluation_worker"))
    return workers


def report(settings):
    print("Configuration: OK; existing non-empty settings and keys preserved.", flush=True)
    print("Workers: " + ", ".join(name for name, _ in worker_modules(settings)), flush=True)
    if not settings.smtp_configured:
        print("SMTP is not configured: registration/reset emails cannot be delivered. "
              "Fill SMTP_* in backend/.env, then restart.", flush=True)
    if not settings.agent_dispatch_enabled:
        print("Agent dispatch is disabled; configure a transport/model before enabling research.", flush=True)


def initialize(root, *, external_db):
    require_tools(docker=not external_db)
    prepare_configuration(root)
    settings = read_settings(root)
    validate_configuration(settings)
    if not external_db:
        validate_database(root, settings)
    print("Installing frontend dependencies...", flush=True)
    run_command([npm_command(), "ci"], root / "frontend")
    if not external_db:
        run_command(["docker", "compose", "up", "-d", "--wait", "postgres"], root / "backend")
    print("Applying database migrations (back up an existing database first)...", flush=True)
    run_command([sys.executable, "-m", "alembic", "upgrade", "head"], root / "backend")
    report(settings)
    print("Initialization complete. Run start to launch the services.", flush=True)


@contextmanager
def service_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ServiceError("Another init/start process holds backend/runtime/service.lock.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ProcessManager:
    def __init__(self, logs):
        self.logs = logs
        self.children = []

    def __enter__(self):
        self.logs.mkdir(parents=True, exist_ok=True)
        return self

    def start(self, name, command, cwd, *, env=None):
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                   if os.name == "nt" else {"start_new_session": True})
        path = self.logs / f"{name}.log"
        with path.open("ab") as output:
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=output,
                                     stderr=subprocess.STDOUT, **options)
        self.children.append((name, child))
        print(f"Started {name}; log: {path}", flush=True)
        return child

    def check(self):
        for name, child in self.children:
            if child.poll() is not None:
                raise ServiceError(f"{name} exited ({child.returncode}); see {self.logs / (name + '.log')}")

    def wait_ready(self, url, *, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.check()
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200 and json.load(response).get("status") == "ready":
                        return
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        raise ServiceError(f"Timed out waiting for readiness: {url}; check service logs and run init.")

    def __exit__(self, *_):
        for _, child in reversed(self.children):
            if os.name == "nt":
                if child.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for _, child in self.children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    child.kill()
                else:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.wait()


def start_services(root, *, external_db=False):
    require_tools(docker=not external_db)
    settings = read_settings(root)
    validate_configuration(settings)
    if not external_db:
        validate_database(root, settings)
    vite = root / "frontend/node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise ServiceError("Frontend dependencies are missing. Run init first.")
    for port in (8000, 5173):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise ServiceError(f"Port {port} is already in use. Check its owner before starting.") from None
    if not external_db:
        run_command(["docker", "compose", "up", "-d", "--wait", "postgres"], root / "backend")
    report(settings)
    with ProcessManager(root / "backend/runtime/services") as manager:
        manager.start("api", [sys.executable, "-u", "-m", "uvicorn", "app.main:create_app",
                             "--factory", "--host", "127.0.0.1", "--port", "8000"], root / "backend")
        manager.wait_ready("http://127.0.0.1:8000/ready")
        for name, module in worker_modules(settings):
            manager.start(name, [sys.executable, "-u", "-m", module], root / "backend")
        environment = {**os.environ, "API_PROXY_TARGET": "http://127.0.0.1:8000", "VITE_API_BASE_URL": ""}
        manager.start("web", ["node", str(vite)], root / "frontend", env=environment)
        manager.wait_ready(WEB_URL + "/ready")
        print(f"Open {WEB_URL} . Ctrl+C stops this launcher's services; PostgreSQL is kept.", flush=True)
        while True:
            manager.check()
            time.sleep(0.5)


def interrupt(*_):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "start", "check"))
    parser.add_argument("--external-db", action="store_true", help="init/start: use an existing database; skip Docker")
    args = parser.parse_args(argv)
    if args.external_db and args.action == "check":
        parser.error("--external-db applies only to init/start")
    signal.signal(signal.SIGTERM, interrupt)
    try:
        if args.action == "check":
            require_tools()
            settings = read_settings(ROOT)
            validate_configuration(settings)
            report(settings)
            print("Configuration/tools check only; no model, SMTP or database connection was attempted.")
        else:
            with service_lock(ROOT / "backend/runtime/service.lock"):
                if args.action == "init":
                    initialize(ROOT, external_db=args.external_db)
                else:
                    start_services(ROOT, external_db=args.external_db)
        return 0
    except KeyboardInterrupt:
        print("Stopped. PostgreSQL and its data volume were preserved.", flush=True)
        return 130
    except ValidationError as error:
        fields = ", ".join(".".join(map(str, item["loc"])) for item in error.errors(include_input=False))
        print(f"Invalid backend configuration fields: {fields}", file=sys.stderr)
    except subprocess.CalledProcessError as error:
        print(f"Command failed (exit {error.returncode}); fix the error above and rerun.", file=sys.stderr)
    except (ServiceError, OSError) as error:
        print(str(error), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
