from pathlib import Path

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
