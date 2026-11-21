from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr
    storage_root: Path = Path(__file__).resolve().parents[2] / "runtime" / "storage"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    task_monitor_enabled: bool = True
    parser_timeout_seconds: float = Field(default=120, ge=1, le=600, allow_inf_nan=False)
    task_runner: Literal["agent"] = "agent"
    agent_dispatch_enabled: bool = False
    agent_exchange_root: Path | None = None
    agent_transport: Literal["manual", "local", "tacc"] = "manual"
    agent_local_root: Path | None = None
    agent_local_python: Path | None = None
    agent_tacc_host: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    agent_tacc_helper: str | None = None
    agent_tacc_config: str | None = None
    agent_tacc_python: str = Field(default="python3", min_length=1, max_length=1024)
    agent_transport_timeout_seconds: float = Field(default=30, ge=1, le=300, allow_inf_nan=False)
    agent_retention_seconds: int = Field(default=604800, ge=86400, le=31536000)
    agent_max_steps: int = Field(default=100, ge=1, le=100)
    agent_search_max_papers: int = Field(default=5, ge=1, le=20)
    agent_timeout_seconds: int = Field(default=1800, ge=60, le=1800)
    agent_output_tokens: int = Field(default=8192, ge=1024, le=32768)
    agent_context_tokens: int = Field(default=32000, ge=4096, le=1000000)
    agent_result_max_bytes: int = Field(default=16 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    agent_poll_seconds: float = Field(default=2, ge=0.1, le=30, allow_inf_nan=False)
    frontend_public_url: str = "http://127.0.0.1:5173"
    auth_cookie_secure: bool = False
    auth_session_ttl_seconds: int = Field(default=604800, ge=60, le=604800)
    auth_verify_ttl_seconds: int = Field(default=86400, ge=60, le=86400)
    auth_reset_ttl_seconds: int = Field(default=1800, ge=60, le=3600)
    auth_rate_key: SecretStr | None = None
    auth_csrf_key: SecretStr | None = None
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_auth_code: SecretStr | None = None
    smtp_from: str | None = None
    smtp_timeout_seconds: float = Field(default=15, ge=1, le=60)
    mail_outbox_key: SecretStr | None = None
    user_active_tasks: int = Field(default=2, ge=1, le=100)
    user_active_imports: int = Field(default=2, ge=1, le=100)
    user_daily_tasks: int = Field(default=20, ge=1, le=10000)
    arxiv_enabled: bool = False
    arxiv_contact_email: str | None = None

    @field_validator("arxiv_contact_email")
    @classmethod
    def validate_arxiv_contact(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        from app.sources.arxiv_transport import SupervisedArxivTransport

        SupervisedArxivTransport(value, lambda: None)
        return value

    @property
    def auth_configured(self) -> bool:
        return bool(self.auth_rate_key and self.auth_rate_key.get_secret_value() and self.auth_csrf_key and self.auth_csrf_key.get_secret_value())

    @property
    def smtp_configured(self) -> bool:
        return bool(self.auth_configured and self.smtp_username and self.smtp_auth_code and self.smtp_auth_code.get_secret_value() and self.smtp_from and self.mail_outbox_key and self.mail_outbox_key.get_secret_value())

    @field_validator("frontend_public_url")
    @classmethod
    def validate_frontend_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("FRONTEND_PUBLIC_URL must be an HTTP(S) origin without credentials")
        return value.rstrip("/")

    @property
    def arxiv_configured(self) -> bool:
        return self.arxiv_enabled and bool(self.arxiv_contact_email)

    @field_validator("agent_exchange_root", "agent_local_root", "agent_local_python", "agent_tacc_host", "agent_tacc_helper", "agent_tacc_config", mode="before")
    @classmethod
    def empty_agent_optional_value(cls, value):
        return None if value == "" else value

    @property
    def resolved_agent_exchange_root(self) -> Path:
        value = self.agent_exchange_root
        if value is None:
            return self.storage_root / "agent-exchange"
        if not value.is_absolute():
            value = Path(__file__).resolve().parents[2] / value
        return value.absolute()

    @field_validator("storage_root")
    @classmethod
    def normalize_storage_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            value = Path(__file__).resolve().parents[2] / value
        return value.resolve()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if url.drivername not in {"postgresql", "postgresql+psycopg"} or not url.database:
                raise ValueError
        except (ArgumentError, ValueError):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL with a database name; "
                "use postgresql+psycopg://user:password@host:port/database"
            ) from None
        if any(key.casefold() in {"password", "sslpassword"} for key in url.query):
            raise ValueError(
                "DATABASE_URL does not support password or sslpassword query parameters; "
                "put the connection password in the URL userinfo before @"
            )
        return SecretStr(
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
        )
