"""Render the local web/TACC configuration from one private dotenv file."""
import fcntl
import os
import secrets
import tempfile
from contextlib import ExitStack
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key
from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy.engine import make_url

from app.auth.security import check_config
from app.config import Settings


def stage_env(path, changes, cleanup):
    template = path.with_name(".env.example")
    existing = dotenv_values(path, interpolate=False)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        staged = Path(tmp.name)
        cleanup.callback(staged.unlink, missing_ok=True)
        tmp.write((path if path.exists() else template).read_bytes())
    if path.exists():
        for key, value in dotenv_values(template, interpolate=False).items():
            if key not in existing and key not in changes:
                set_key(str(staged), key, value or "")
    for key, value in changes.items():
        if existing.get(key) != value or not path.exists():
            set_key(str(staged), key, value)
    return staged


def configure(root):
    backend = root / "backend" / ".env"
    agent = root / "agent" / ".env"
    source = root / ".env.local-research"
    with source.open() as handle, ExitStack() as cleanup:
        fcntl.flock(handle, fcntl.LOCK_EX)
        source.chmod(0o600)
        form = dotenv_values(stream=handle, interpolate=False)
        old = dotenv_values(backend, interpolate=False)
        model = dotenv_values(agent, interpolate=False)
        sender = form.get("SMTP_USERNAME") or old.get("SMTP_USERNAME")
        auth = form.get("SMTP_AUTH_CODE") or old.get("SMTP_AUTH_CODE")
        key = form.get("BAILIAN_API_KEY") or model.get("BAILIAN_API_KEY")
        for name, value in (("SMTP_USERNAME", sender), ("SMTP_AUTH_CODE", auth), ("BAILIAN_API_KEY", key)):
            if not value:
                raise SystemExit(f"请在 .env.local-research 填写 {name}")
        host = form.get("SMTP_HOST")
        if not host:
            host = {"qq.com": "smtp.qq.com", "163.com": "smtp.163.com"}.get(sender.split("@")[-1].lower())
        if not host and sender == old.get("SMTP_USERNAME"):
            host = old.get("SMTP_HOST")
        if not host:
            raise SystemExit("请填写发件邮箱的 SMTP_HOST（SSL 465）")

        updates = dict(SMTP_HOST=host, SMTP_PORT="465", SMTP_USERNAME=sender, SMTP_FROM=sender,
                       SMTP_AUTH_CODE=auth, ARXIV_ENABLED="true",
                       ARXIV_CONTACT_EMAIL=form.get("ARXIV_CONTACT_EMAIL") or old.get("ARXIV_CONTACT_EMAIL") or sender,
                       TASK_RUNNER="agent", AGENT_DISPATCH_ENABLED="true", AGENT_TRANSPORT="tcloud",
                       AGENT_TCLOUD_MODEL_ENV_FILE=str(agent))
        if form.get("AGENT_TCLOUD_ENV_NAME"):
            updates["AGENT_TCLOUD_ENV_NAME"] = form["AGENT_TCLOUD_ENV_NAME"]
        for name in ("AUTH_RATE_KEY", "AUTH_CSRF_KEY"):
            if not old.get(name):
                updates[name] = secrets.token_hex(32)
        if not old.get("MAIL_OUTBOX_KEY"):
            updates["MAIL_OUTBOX_KEY"] = Fernet.generate_key().decode()
        if not backend.exists():
            password = secrets.token_hex(24)
            updates.update(POSTGRES_PASSWORD=password,
                           DATABASE_URL=f"postgresql+psycopg://literature:{password}@127.0.0.1:5432/literature")

        model_updates = {"MODEL_PROVIDER": "bailian", "BAILIAN_API_KEY": key}
        for name in ("MODEL_BASE_URL", "MODEL_NAME", "TAVILY_API_KEY",
                     "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS"):
            if form.get(name):
                model_updates[name] = form[name]
        persist = (form.get("AGENT_PERSIST") or old.get("AGENT_PERSIST") or "false").lower()
        if persist not in {"true", "false"}:
            raise SystemExit("AGENT_PERSIST 必须为 true 或 false")
        updates["AGENT_PERSIST"] = persist
        updates["TAVILY_API_KEY"] = model_updates.get("TAVILY_API_KEY") or model.get("TAVILY_API_KEY") or ""
        staged_backend = stage_env(backend, updates, cleanup)
        check_config(Settings(_env_file=staged_backend), mail=True)
        agent_db = form.get("AGENT_DATABASE_URL")
        if agent_db == "local":
            local = make_url(dotenv_values(staged_backend)["DATABASE_URL"])
            if local.host not in {"127.0.0.1", "localhost", "::1"}:
                raise SystemExit("AGENT_DATABASE_URL=local 需要使用本机 PostgreSQL 的后端连接串")
            local = local.set(drivername="postgresql")
            if "sslmode" not in local.query:
                local = local.update_query_dict({"sslmode": "disable"})
            agent_db = local.render_as_string(hide_password=False)
        if agent_db:
            try:
                conninfo_to_dict(agent_db)
            except ProgrammingError:
                raise SystemExit("AGENT_DATABASE_URL 需要有效的 PostgreSQL 连接串或 local") from None
            model_updates["DATABASE_URL"] = agent_db
        destination = model_updates.get("DATABASE_URL") or model.get("DATABASE_URL")
        if persist == "true" and not destination:
            raise SystemExit("启用 AGENT_PERSIST 需要 AGENT_DATABASE_URL")
        set_key(str(staged_backend), "AGENT_PERSIST_DATABASE_URL", destination if persist == "true" else "")
        staged_agent = stage_env(agent, model_updates, cleanup)
        os.replace(staged_agent, agent)
        os.replace(staged_backend, backend)
    print("已配置 backend/.env 和 agent/.env。启动或重启服务后生效。")


if __name__ == "__main__":
    os.umask(0o077)
    configure(Path(__file__).resolve().parents[1])
