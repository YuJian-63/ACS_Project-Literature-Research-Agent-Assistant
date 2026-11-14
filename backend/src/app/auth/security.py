import hashlib
import hmac
import re
import secrets
from functools import lru_cache
from urllib.parse import urlsplit

from app.errors import APIError


RESERVED_NAMES = {"admin", "administrator", "root", "system", "support", "api", "auth", "postmaster", "abuse"}


def normalize_username(value: str) -> tuple[str, str]:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", value) or value.lower() in RESERVED_NAMES:
        raise ValueError("Username must be 3-32 ASCII letters, digits or underscores and not reserved")
    return value, value.lower()


def normalize_email(value: str) -> tuple[str, str]:
    value = value.strip()
    if len(value) > 254 or value.count("@") != 1 or any(ord(character) < 33 for character in value):
        raise ValueError("Invalid email address")
    local, domain = value.rsplit("@", 1)
    if (not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}", local)
            or local.startswith(".") or local.endswith(".") or ".." in local):
        raise ValueError("Invalid email address")
    labels = domain.split(".")
    if len(labels) < 2 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels):
        raise ValueError("Invalid email address")
    return value, value.lower()


def validate_password(value: str) -> str:
    if not 6 <= len(value) <= 128:
        raise ValueError("Password must contain 6-128 characters")
    value.encode("utf-8")
    return value


@lru_cache(maxsize=1)
def password_hasher():
    try:
        from argon2 import PasswordHasher, Type
    except ImportError:
        raise unavailable() from None
    return PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16, type=Type.ID)


def hash_password(value: str) -> str:
    return password_hasher().hash(validate_password(value))


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))


def verify_password(encoded: str | None, value: str) -> bool:
    hasher = password_hasher()
    from argon2.exceptions import InvalidHashError, VerificationError
    if len(value) > 128:
        return False
    try:
        valid = hasher.verify(encoded or dummy_hash(), value)
        return bool(encoded) and valid
    except (InvalidHashError, VerificationError, UnicodeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def keyed_hash(key, value: str) -> str:
    return hmac.new(key.get_secret_value().encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def csrf_token(settings, raw_session: str) -> str:
    return keyed_hash(settings.auth_csrf_key, "csrf:" + raw_session)


def cookie_name(settings) -> str:
    return "__Host-lra_session" if settings.auth_cookie_secure else "lra_dev_session"


def unavailable() -> APIError:
    return APIError(503, "AUTH_UNAVAILABLE", "Account service is not configured")


def check_config(settings, *, mail: bool = False) -> None:
    try:
        parsed = urlsplit(settings.frontend_public_url)
        valid_url = (parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
                     and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                     and parsed.path in {"", "/"})
        safe_cookie = (parsed.scheme == "https" if settings.auth_cookie_secure
                       else parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        signing_keys = (settings.auth_rate_key, settings.auth_csrf_key)
        keys = all(key and len(key.get_secret_value().encode()) >= 32 for key in signing_keys)
        independent = keys and settings.auth_rate_key.get_secret_value() != settings.auth_csrf_key.get_secret_value()
        lifetimes = (60 <= settings.auth_session_ttl_seconds <= 604800
                     and 60 <= settings.auth_verify_ttl_seconds <= 86400
                     and 60 <= settings.auth_reset_ttl_seconds <= 3600)
        if not settings.auth_configured or not valid_url or not safe_cookie or not independent or not lifetimes:
            raise unavailable()
        if mail:
            from cryptography.fernet import Fernet
            if (not settings.smtp_configured or not settings.mail_outbox_key
                    or not settings.smtp_auth_code or not settings.smtp_auth_code.get_secret_value()
                    or not settings.smtp_username or not settings.smtp_from or not settings.smtp_host
                    or settings.smtp_port != 465 or not 0 < settings.smtp_timeout_seconds <= 60
                    or settings.smtp_username.lower() != settings.smtp_from.lower()):
                raise unavailable()
            normalize_email(settings.smtp_from)
            mail_key = settings.mail_outbox_key.get_secret_value()
            if any(mail_key == key.get_secret_value() for key in signing_keys):
                raise unavailable()
            Fernet(mail_key.encode("ascii"))
    except (AttributeError, TypeError, ValueError, UnicodeError, ImportError):
        raise unavailable() from None
