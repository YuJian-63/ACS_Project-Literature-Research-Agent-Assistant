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
    mock_step_delay_seconds: float = Field(default=0.5, ge=0, le=10, allow_inf_nan=False)
    parser_timeout_seconds: float = Field(default=120, ge=1, le=600, allow_inf_nan=False)
    task_runner: Literal["mock", "langgraph", "agent"] = "mock"
    agent_python: str = str(Path(__file__).resolve().parents[3] / "agent" / ".venv" / "bin" / "python")
    llm_base_url: str | None = None
    llm_model_id: str | None = None
    llm_api_key: SecretStr | None = None
    llm_thinking_mode: Literal["provider_default", "disabled", "enabled"] = "provider_default"
    llm_timeout_seconds: float = Field(default=60, ge=1, le=300, allow_inf_nan=False)
    evidence_context_chars: int = Field(default=24000, ge=1000, le=100000)
    retrieval_snapshot_bytes: int = Field(default=8 * 1024 * 1024, ge=100000, le=64 * 1024 * 1024)
    research_context_tokens: int = Field(default=32768, ge=4096, le=1000000)
    research_output_tokens: int = Field(default=8192, ge=1024, le=32768)
    research_task_tokens: int = Field(default=100000, ge=1000, le=100000)
    research_call_timeout_seconds: float = Field(default=180, ge=5, le=300, allow_inf_nan=False)
    review_context_tokens: int = Field(default=32768, ge=4096, le=1000000)
    review_output_tokens: int = Field(default=4096, ge=1024, le=32768)
    review_task_tokens: int = Field(default=100000, ge=1000, le=100000)
    review_timeout_seconds: int = Field(default=1800, ge=60, le=1800)
    review_call_timeout_seconds: float = Field(default=90, ge=5, le=300, allow_inf_nan=False)
    review_evidence_chars: int = Field(default=4000, ge=1000, le=4000)
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

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("LLM_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment")
        return value

    @field_validator("llm_model_id")
    @classmethod
    def validate_llm_model_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or len(value) > 256:
            raise ValueError("LLM_MODEL_ID must contain 1–256 characters")
        return value

    @property
    def real_runner_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model_id and self.llm_api_key and self.llm_api_key.get_secret_value())

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
