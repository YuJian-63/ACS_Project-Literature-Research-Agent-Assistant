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
    storage_root: Path = Path(__file__).resolve().parents[2] / "runtime" / "v3" / "storage"
    cors_origins: list[str] = ["http://localhost:5175", "http://127.0.0.1:5175"]
    parser_timeout_seconds: float = Field(default=120, ge=1, le=600, allow_inf_nan=False)
    frontend_public_url: str = "http://127.0.0.1:5175"
    auth_cookie_name: str = "lra_v3_session"
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
    user_active_imports: int = Field(default=2, ge=1, le=100)
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
            if url.drivername not in {"postgresql", "postgresql+psycopg"} or not url.database or not (url.database == "literature_v3" or url.database.startswith("literature_v3_test_")):
                raise ValueError
        except (ArgumentError, ValueError):
            raise ValueError(
                "DATABASE_URL must use literature_v3 or an isolated literature_v3_test_* database; "
                "use postgresql+psycopg://user:password@host:port/database"
            ) from None
        overrides = {"dbname", "database", "service", "host", "hostaddr", "port", "user"}
        if any(key.casefold() in overrides for key in url.query):
            raise ValueError("DATABASE_URL query parameters cannot override the isolated connection target")
        if any(key.casefold() in {"password", "sslpassword"} for key in url.query):
            raise ValueError(
                "DATABASE_URL does not support password or sslpassword query parameters; "
                "put the connection password in the URL userinfo before @"
            )
        return SecretStr(
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
        )
