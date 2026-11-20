import base64
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from pydantic import SecretStr


def settings(**overrides):
    values = dict(
        frontend_public_url="http://localhost:5175", auth_cookie_secure=False,
        auth_session_ttl_seconds=604800, auth_verify_ttl_seconds=86400,
        auth_reset_ttl_seconds=1800, auth_rate_key=SecretStr("test-rate-key-" * 4),
        auth_csrf_key=SecretStr("test-csrf-key-" * 4), auth_configured=True,
        smtp_configured=True, smtp_host="smtp.invalid", smtp_port=465,
        smtp_username="sender@example.com", smtp_auth_code=SecretStr("fixture-code"),
        smtp_from="sender@example.com", smtp_timeout_seconds=5,
        mail_outbox_key=SecretStr(base64.urlsafe_b64encode(b"0" * 32).decode()),
    )
    return SimpleNamespace(**(values | overrides))


class SecurityTests(unittest.TestCase):
    def test_database_harness_refuses_acceptance_and_nonlocal_targets(self):
        for database in ("literature_v3_test_auth", "literature_v3_test_auth_" + "a" * 32):
            self.assertTrue(isolated_postgres_target("postgresql+psycopg://localhost/" + database))
        for url in ("postgresql://localhost/literature_acceptance",
                    "postgresql://example.com/literature_v3_test_auth", "sqlite:///literature_v3_test_auth",
                    "postgresql://localhost/literature_v3_test_auth_acceptance", "invalid",
                    "postgresql://localhost/literature_v3_test_auth?dbname=literature_acceptance",
                    "postgresql://localhost/literature_v3_test_auth?host=example.com",
                    "postgresql://localhost/literature_v3_test_auth?service=acceptance"):
            with self.subTest(url=url):
                self.assertFalse(isolated_postgres_target(url))

    def test_username_normalization_and_reserved_names(self):
        from app.auth.security import normalize_username
        self.assertEqual(normalize_username("  Alice_1  "), ("Alice_1", "alice_1"))
        for value in ("ab", "a" * 33, "a-b", "Admin", "root", "support"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_username(value)

    def test_email_preserves_plus_and_dots_and_rejects_headers(self):
        from app.auth.security import normalize_email
        self.assertEqual(normalize_email("  A.B+tag@Example.COM "),
                         ("A.B+tag@Example.COM", "a.b+tag@example.com"))
        for value in ("a@localhost", "a..b@example.com", "a@-bad.com", "a@b.com\r\nBcc: x@y.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_email(value)

    def test_argon2_salts_passwords_and_never_trims_them(self):
        from app.auth.security import hash_password, verify_password
        password = "  long enough password  "
        first, second = hash_password(password), hash_password(password)
        self.assertTrue(first.startswith("$argon2id$"))
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(first, password))
        self.assertFalse(verify_password(first, password.strip()))
        self.assertFalse(verify_password(None, password))
        self.assertFalse(verify_password("broken", password))
        for value in ("x" * 5, "x" * 129):
            with self.assertRaises(ValueError):
                hash_password(value)

    def test_password_policy_accepts_six_characters_without_character_mix(self):
        from app.auth.api import ChangeInput, RegisterInput, TokenInput
        from app.auth.security import hash_password, validate_password, verify_password
        from pydantic import ValidationError
        for password in ("123456", "abcdef", "______", "ab_123", "!@#$%^", "x" * 128):
            with self.subTest(password=password):
                self.assertEqual(validate_password(password), password)
                self.assertTrue(verify_password(hash_password(password), password))
                self.assertEqual(RegisterInput(username="Alice", email="alice@example.com", password=password).password, password)
                self.assertEqual(TokenInput(token="t" * 43, password=password).password, password)
                self.assertEqual(ChangeInput(current_password="old_password", password=password).password, password)
        for password in ("", "12345", "x" * 129):
            with self.subTest(length=len(password)):
                with self.assertRaises(ValueError):
                    validate_password(password)
                for model, fields in ((RegisterInput, {"username": "Alice", "email": "alice@example.com"}),
                                      (TokenInput, {"token": "t" * 43}),
                                      (ChangeInput, {"current_password": "old_password"})):
                    with self.assertRaises(ValidationError):
                        model(password=password, **fields)

    def test_tokens_and_session_bound_csrf(self):
        from app.auth.security import csrf_token, new_token, token_hash
        first, second = new_token(), new_token()
        self.assertGreaterEqual(len(first), 43)
        self.assertNotEqual(first, second)
        self.assertEqual(len(token_hash(first)), 64)
        self.assertNotEqual(csrf_token(settings(), first), csrf_token(settings(), second))
        self.assertNotEqual(csrf_token(settings(), first),
                            csrf_token(settings(auth_csrf_key=SecretStr("different" * 5)), first))

    def test_password_validation_accepts_unicode_but_rejects_lone_surrogates(self):
        from app.auth.security import validate_password
        password = "\u5bc6\u7801" * 8 + "  "
        self.assertEqual(validate_password(password), password)
        with self.assertRaises(ValueError):
            validate_password("x" * 15 + "\ud800")

    def test_cookie_modes_and_configuration_fail_closed(self):
        from app.auth.security import check_config, cookie_name
        from app.errors import APIError
        self.assertTrue(cookie_name(settings(auth_cookie_secure=True)).startswith("__Host-"))
        self.assertNotEqual(cookie_name(settings()), cookie_name(settings(auth_cookie_secure=True)))
        for config in (settings(auth_configured=False), settings(auth_csrf_key=None),
                       settings(auth_rate_key=None), settings(frontend_public_url="https://user:pw@example.com")):
            with self.assertRaises(APIError) as caught:
                check_config(config)
            self.assertEqual(caught.exception.status_code, 503)
            self.assertNotIn("pw", str(caught.exception.error))

    def test_configuration_requires_independent_keys_and_seven_day_sessions(self):
        from app.auth.security import check_config
        from app.errors import APIError
        for config in (
            settings(auth_csrf_key=settings().auth_rate_key),
            settings(auth_session_ttl_seconds=604801),
            settings(auth_session_ttl_seconds=0),
            settings(auth_verify_ttl_seconds=86401),
            settings(auth_reset_ttl_seconds=0),
        ):
            with self.subTest(config=config.auth_session_ttl_seconds):
                with self.assertRaises(APIError) as caught:
                    check_config(config)
                self.assertEqual(caught.exception.status_code, 503)
        with self.assertRaises(APIError):
            check_config(settings(auth_rate_key=settings().mail_outbox_key), mail=True)

    def test_origin_guard_ignores_forwarded_host_and_requires_exact_origin(self):
        from fastapi import FastAPI
        from starlette.requests import Request
        from app.auth.dependencies import client_ip, require_origin
        from app.errors import APIError
        app = FastAPI()
        app.state.settings = settings()
        for origin in (None, "null", "http://localhost:5175.evil.invalid", "http://localhost:5175/"):
            headers = [(b"x-forwarded-for", b"203.0.113.5")]
            if origin is not None:
                headers.append((b"origin", origin.encode()))
            request = Request({"type": "http", "app": app, "method": "POST", "headers": headers,
                               "client": ("127.0.0.9", 1234)})
            with self.assertRaises(APIError):
                require_origin(request)
            self.assertEqual(client_ip(request), "127.0.0.9")

    def test_private_response_middleware_sets_no_store_on_errors(self):
        import asyncio
        from app.auth.dependencies import AuthResponseMiddleware
        result = []
        async def application(scope, receive, send):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b""})
        async def send(message):
            result.append(message)
        asyncio.run(AuthResponseMiddleware(application)({"type": "http", "path": "/api/v1/private"}, None, send))
        headers = dict(result[0]["headers"])
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(headers[b"referrer-policy"], b"no-referrer")

    def test_missing_crypto_dependencies_fail_closed_with_sanitized_503(self):
        import builtins
        from unittest.mock import patch
        from app.auth.security import check_config, hash_password, password_hasher
        from app.errors import APIError
        original = builtins.__import__
        def unavailable_import(name, *args, **kwargs):
            if name.split(".")[0] in {"argon2", "cryptography"}:
                raise ImportError("private installation paths must not be returned")
            return original(name, *args, **kwargs)
        password_hasher.cache_clear()
        with patch("builtins.__import__", side_effect=unavailable_import):
            for action in (lambda: hash_password("a long fixture password"), lambda: check_config(settings(), mail=True)):
                with self.assertRaises(APIError) as caught:
                    action()
                self.assertEqual(caught.exception.status_code, 503)
                self.assertNotIn("private installation", str(caught.exception.error))

    def test_mail_encryption_fragment_urls_and_tamper_detection(self):
        from app.auth.mail import decrypt_payload, encrypt_payload, make_payload
        from cryptography.fernet import InvalidToken
        payload = make_payload(settings(), "verify_email", "recipient@example.com", "Alice", "opaque-secret", "en")
        self.assertIn("/verify-email#token=opaque-secret", payload["body"])
        self.assertNotIn("?token=", payload["body"])
        ciphertext = encrypt_payload(settings(), payload)
        self.assertNotIn("opaque-secret", ciphertext)
        self.assertNotIn("recipient@example.com", ciphertext)
        self.assertEqual(decrypt_payload(settings(), ciphertext), payload)
        with self.assertRaises(InvalidToken):
            decrypt_payload(settings(), ciphertext[:-8] + "AAAAAAAA")

    def test_chinese_mail_payload_has_readable_utf8_subject_and_body(self):
        from app.auth.mail import decrypt_payload, encrypt_payload, make_payload
        for purpose, subject, minutes in (("verify_email", "验证邮箱", 1440),
                                          ("reset_password", "重置密码", 30)):
            with self.subTest(purpose=purpose):
                payload = make_payload(settings(), purpose, "alice@example.com", "Alice", "secret", "zh")
                self.assertEqual(payload["subject"], subject)
                self.assertIn("你好 Alice", payload["body"])
                self.assertIn(f"{minutes} 分钟", payload["body"])
                self.assertIn("请忽略此邮件", payload["body"])
                self.assertIn("#token=secret", payload["body"])
                self.assertNotIn("?", payload["body"])
                self.assertEqual(decrypt_payload(settings(), encrypt_payload(settings(), payload)), payload)

    def test_smtp_uses_ssl_verified_context_and_finite_timeout(self):
        import ssl
        from unittest.mock import patch
        from app.auth.mail import send_payload
        with patch("app.auth.mail.smtplib.SMTP_SSL") as smtp:
            send_payload(settings(), {"to": "recipient@example.com", "subject": "Fixture", "body": "Fixture message"})
        call = smtp.call_args
        self.assertEqual(call.args[:2], ("smtp.invalid", 465))
        self.assertEqual(call.kwargs["timeout"], 5)
        self.assertEqual(call.kwargs["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(call.kwargs["context"].check_hostname)
        smtp.return_value.__enter__.return_value.login.assert_called_once_with("sender@example.com", "fixture-code")

    def test_smtp_has_a_total_attempt_deadline(self):
        import time
        from unittest.mock import patch
        from app.auth.mail import send_payload
        def slow_connection(*args, **kwargs):
            time.sleep(0.2)
        started = time.monotonic()
        with patch("app.auth.mail.smtplib.SMTP_SSL", side_effect=slow_connection):
            with self.assertRaises(TimeoutError):
                send_payload(settings(smtp_timeout_seconds=0.05),
                             {"to": "recipient@example.com", "subject": "Fixture", "body": "Fixture"})
        self.assertLess(time.monotonic() - started, 1)


class AuthBehaviorTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import MetaData, create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.db.models import AuthEmailToken, AuthMailOutbox, AuthRateBucket, AuthSession, User
        self.models = (User, AuthSession, AuthEmailToken, AuthMailOutbox, AuthRateBucket)
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata = MetaData()
        for model in self.models:
            table = model.__table__.to_metadata(metadata)
            for column in table.columns:
                column.server_default = None
        metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.settings = settings()
        from app.auth.service import AuthService
        self.auth = AuthService(self.sessions, self.settings)
        self.password = "a long fixture password"

    def tearDown(self):
        self.engine.dispose()

    def register(self, username="Alice", email="alice@example.com"):
        self.auth.register(username, email, self.password, "127.0.0.1", "en")
        return self.latest_token("verify_email")

    def latest_token(self, purpose):
        from sqlalchemy import select
        from app.auth.mail import decrypt_payload
        from app.db.models import AuthEmailToken, AuthMailOutbox
        with self.sessions() as session:
            row = session.scalar(select(AuthMailOutbox).join(AuthEmailToken, AuthEmailToken.id == AuthMailOutbox.token_id)
                                 .where(AuthEmailToken.purpose == purpose, AuthEmailToken.revoked_at.is_(None))
                                 .order_by(AuthMailOutbox.created_at.desc(), AuthMailOutbox.id.desc()))
            return decrypt_payload(self.settings, row.payload_ciphertext)["body"].split("#token=", 1)[1].split()[0]

    def activate(self):
        token = self.register()
        self.auth.verify_email(token, self.password, "127.0.0.1")

    def test_pending_registration_requires_token_and_original_password(self):
        from app.errors import APIError
        token = self.register()
        with self.assertRaises(APIError) as caught:
            self.auth.login("alice", self.password, "127.0.0.1")
        self.assertEqual(caught.exception.error["code"], "EMAIL_NOT_VERIFIED")
        with self.assertRaises(APIError):
            self.auth.verify_email(token, "wrong password", "127.0.0.1")
        self.auth.verify_email(token, self.password, "127.0.0.1")
        user, raw = self.auth.login("ALICE", self.password, "127.0.0.1")
        self.assertEqual(user.username, "Alice")
        self.assertEqual(self.auth.authenticate(raw)[0].id, user.id)
        with self.assertRaises(APIError):
            self.auth.verify_email(token, self.password, "127.0.0.1")

    def test_duplicate_registration_cannot_overwrite_password(self):
        from sqlalchemy import select
        from app.db.models import User
        from app.errors import APIError
        self.register()
        with self.assertRaises(APIError):
            self.auth.register("ALICE", "other@example.com", "different long password", "127.0.0.2", "en")
        with self.sessions() as session:
            user = session.scalar(select(User))
            self.assertEqual(user.email, "alice@example.com")
            self.assertEqual(user.status, "pending")

    def test_wrong_password_does_not_reveal_pending_status(self):
        from app.errors import APIError
        self.register()
        errors = []
        for name in ("Alice", "Nonexistent"):
            with self.assertRaises(APIError) as caught:
                self.auth.login(name, "wrong password", "127.0.0.1")
            errors.append(caught.exception.error)
        self.assertEqual(errors[0], errors[1])

    def test_reset_revokes_every_session_and_consumes_token_once(self):
        from app.errors import APIError
        self.activate()
        first = self.auth.login("alice", self.password, "127.0.0.1")[1]
        second = self.auth.login("alice", self.password, "127.0.0.1")[1]
        self.clear_rates()
        self.auth.email_request("alice@example.com", "reset_password", "127.0.0.1", "en")
        token = self.latest_token("reset_password")
        with self.assertRaises(ValueError):
            self.auth.reset_password(token, "short", "127.0.0.1")
        self.auth.reset_password(token, "a different long password", "127.0.0.1")
        for raw in (first, second):
            with self.assertRaises(APIError):
                self.auth.authenticate(raw)
        with self.assertRaises(APIError):
            self.auth.reset_password(token, self.password, "127.0.0.1")
        self.auth.login("alice", "a different long password", "127.0.0.1")

    def clear_rates(self):
        from sqlalchemy import delete
        from app.db.models import AuthRateBucket
        with self.sessions.begin() as session:
            session.execute(delete(AuthRateBucket))

    def test_unknown_pending_disabled_forgot_return_same_result(self):
        from sqlalchemy import func, select
        from app.db.models import AuthMailOutbox
        self.register()
        self.clear_rates()
        self.assertIsNone(self.auth.email_request("unknown@example.com", "reset_password", "127.0.0.1", "en"))
        self.assertIsNone(self.auth.email_request("alice@example.com", "reset_password", "127.0.0.2", "en"))
        self.activate_existing_pending()
        from app.db.models import User
        with self.sessions.begin() as session:
            session.scalar(select(User)).status = "disabled"
        self.clear_rates()
        self.assertIsNone(self.auth.email_request("alice@example.com", "reset_password", "127.0.0.3", "en"))
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AuthMailOutbox)), 1)

    def activate_existing_pending(self):
        self.auth.verify_email(self.latest_token("verify_email"), self.password, "127.0.0.1")

    def test_expired_wrong_purpose_and_disabled_tokens_cannot_be_consumed(self):
        from app.auth.service import db_now
        from app.db.models import AuthEmailToken, User
        from app.errors import APIError
        from sqlalchemy import select
        token = self.register()
        with self.assertRaises(APIError):
            self.auth.reset_password(token, self.password, "127.0.0.1")
        with self.sessions.begin() as session:
            session.scalar(select(AuthEmailToken)).expires_at = db_now(session) - timedelta(seconds=1)
        with self.assertRaises(APIError):
            self.auth.verify_email(token, self.password, "127.0.0.1")
        with self.sessions.begin() as session:
            row = session.scalar(select(AuthEmailToken))
            self.assertIsNone(row.consumed_at)
            row.expires_at = db_now(session) + timedelta(hours=1)
            session.scalar(select(User)).status = "disabled"
        with self.assertRaises(APIError):
            self.auth.verify_email(token, self.password, "127.0.0.1")

    def test_expired_pending_can_be_replaced_but_live_pending_cannot(self):
        from app.auth.service import db_now
        from app.db.models import User
        from sqlalchemy import select
        self.register()
        self.clear_rates()
        with self.sessions.begin() as session:
            user = session.scalar(select(User))
            old_id = user.id
            user.created_at = db_now(session) - timedelta(days=2)
            user.updated_at = user.created_at
        self.auth.register("Alice", "alice@example.com", "another long password", "127.0.0.1", "en")
        with self.sessions() as session:
            user = session.scalar(select(User))
            self.assertNotEqual(user.id, old_id)

    def test_email_cooldown_shared_across_public_mail_endpoints(self):
        from app.errors import APIError
        self.register()
        with self.assertRaises(APIError) as caught:
            self.auth.email_request("ALICE@example.com", "verify_email", "127.0.0.2", "en")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertGreater(int(caught.exception.headers["Retry-After"]), 0)

    def test_mail_configuration_failure_is_sanitized_and_does_not_break_login(self):
        from app.auth.service import AuthService
        from app.errors import APIError
        self.activate()
        other = AuthService(self.sessions, settings(smtp_configured=False, smtp_auth_code=None, mail_outbox_key=None))
        other.login("alice", self.password, "127.0.0.1")
        with self.assertRaises(APIError) as caught:
            other.email_request("alice@example.com", "reset_password", "127.0.0.1", "en")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("alice", str(caught.exception.error))

    def test_resend_revokes_old_token_and_mail(self):
        from app.errors import APIError
        old = self.register()
        self.clear_rates()
        self.auth.email_request("alice@example.com", "verify_email", "127.0.0.1", "en")
        new = self.latest_token("verify_email")
        self.assertNotEqual(old, new)
        with self.assertRaises(APIError):
            self.auth.verify_email(old, self.password, "127.0.0.1")
        self.auth.verify_email(new, self.password, "127.0.0.1")

    def test_change_password_preserves_current_session_and_revokes_others(self):
        from app.errors import APIError
        self.activate()
        user, raw = self.auth.login("alice", self.password, "127.0.0.1")
        _, other = self.auth.login("alice", self.password, "127.0.0.1")
        with self.assertRaises(APIError) as failure:
            self.auth.change_password(user.id, raw, "incorrect", "a different long password", "127.0.0.1")
        self.assertEqual(failure.exception.status_code, 400)
        self.assertEqual(failure.exception.error["code"], "CURRENT_PASSWORD_INCORRECT")
        self.auth.authenticate(raw)
        self.auth.authenticate(other)
        self.auth.change_password(user.id, raw, self.password, "a different long password", "127.0.0.1")
        self.auth.authenticate(raw)
        with self.assertRaises(APIError):
            self.auth.authenticate(other)
        with self.assertRaises(APIError):
            self.auth.login("alice", self.password, "127.0.0.1")
        self.auth.login("alice", "a different long password", "127.0.0.1")

    def test_expiry_auth_version_disable_and_logout(self):
        from app.auth.service import db_now
        from app.db.models import AuthSession, User
        from app.errors import APIError
        from sqlalchemy import select
        self.activate()
        user, raw = self.auth.login("alice", self.password, "127.0.0.1")
        self.auth.logout(raw)
        with self.assertRaises(APIError):
            self.auth.authenticate(raw)
        for mode in ("expiry", "version", "disabled"):
            raw = self.auth.login("alice", self.password, "127.0.0.1")[1]
            with self.sessions.begin() as session:
                account = session.get(User, user.id)
                if mode == "expiry":
                    row = session.scalar(select(AuthSession).where(AuthSession.revoked_at.is_(None)).order_by(AuthSession.created_at.desc()))
                    row.expires_at = db_now(session) - timedelta(seconds=1)
                elif mode == "version":
                    account.auth_version += 1
                else:
                    account.status = "disabled"
            with self.assertRaises(APIError):
                self.auth.authenticate(raw)

    def test_rate_limit_is_persistent_and_does_not_store_email_or_ip(self):
        from app.errors import APIError
        from app.auth.service import AuthService
        from app.db.models import AuthRateBucket
        from sqlalchemy import select
        for attempt in range(10):
            with self.assertRaises(APIError) as caught:
                self.auth.login("Alice", "bad", "192.0.2.5")
            self.assertEqual(caught.exception.status_code, 401)
        other = AuthService(self.sessions, self.settings)
        with self.assertRaises(APIError) as caught:
            other.login("alice", "bad", "192.0.2.6")
        self.assertEqual(caught.exception.status_code, 429)
        with self.sessions() as session:
            for key in session.scalars(select(AuthRateBucket.bucket_key)):
                self.assertNotIn("alice", key)
                self.assertNotIn("192.0.2", key)

    def test_atomic_rate_buckets_expire_and_enforce_across_service_instances(self):
        from app.auth.service import AuthService, db_now
        from app.db.models import AuthRateBucket
        from app.errors import APIError
        from sqlalchemy import select
        self.auth.limits([("test", "private-target", 1, 60)])
        other = AuthService(self.sessions, self.settings)
        with self.assertRaises(APIError) as caught:
            other.limits([("test", "private-target", 1, 60)])
        self.assertEqual(caught.exception.status_code, 429)
        with self.sessions.begin() as session:
            row = session.scalar(select(AuthRateBucket))
            self.assertEqual(row.count, 2)
            row.expires_at = db_now(session) - timedelta(seconds=1)
        self.auth.limits([("test", "private-target", 1, 60)])
        with self.sessions() as session:
            row = session.scalar(select(AuthRateBucket))
            self.assertEqual(row.count, 1)

    def test_http_guard_rejects_cross_session_csrf_and_ignores_proxy_headers(self):
        from fastapi import Depends, FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from app.auth.dependencies import AuthResponseMiddleware, require_user
        from app.auth.security import cookie_name, csrf_token, new_token, token_hash
        from app.auth.service import db_now
        from app.db.models import AuthSession, User
        from app.errors import APIError
        first, second = new_token(), new_token()
        with self.sessions.begin() as session:
            now = db_now(session)
            user = User(id=uuid4(), username="Guard", username_key="guard", email="guard@example.com",
                        email_key="guard@example.com", password_hash="unused-by-guard", status="active",
                        auth_version=1, email_verified_at=now, created_at=now, updated_at=now)
            session.add(user)
            session.flush()
            for raw in (first, second):
                session.add(AuthSession(id=uuid4(), user_id=user.id, token_hash=token_hash(raw), auth_version=1,
                                        expires_at=now + timedelta(hours=1), created_at=now))
        app = FastAPI()
        app.state.sessions, app.state.settings = self.sessions, self.settings
        app.add_middleware(AuthResponseMiddleware)
        @app.exception_handler(APIError)
        async def errors(request, error):
            return JSONResponse({"error": error.error}, status_code=error.status_code)
        @app.post("/api/v1/private")
        def private(user=Depends(require_user)):
            return {"id": str(user.id)}
        with TestClient(app) as client:
            client.cookies.set(cookie_name(self.settings), first)
            headers = {"Origin": "http://localhost:5175", "X-CSRF-Token": csrf_token(self.settings, second)}
            self.assertEqual(client.post("/api/v1/private", headers=headers).status_code, 403)
            headers["X-CSRF-Token"] = csrf_token(self.settings, first)
            self.assertEqual(client.post("/api/v1/private", headers=headers).status_code, 200)
            headers["Origin"] = "http://attacker.invalid"
            headers["X-Forwarded-Host"] = "localhost:5175"
            denied = client.post("/api/v1/private", headers=headers)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.headers["cache-control"], "no-store")
            with self.sessions.begin() as session:
                session.get(User, user.id).auth_version += 1
            headers["Origin"] = "http://localhost:5175"
            self.assertEqual(client.post("/api/v1/private", headers=headers).status_code, 401)

    def test_auth_validation_errors_never_echo_passwords_or_tokens(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from app.auth.api import router
        from app.auth.dependencies import AuthResponseMiddleware
        from app.errors import APIError
        app = FastAPI()
        app.state.sessions, app.state.settings = self.sessions, self.settings
        app.add_middleware(AuthResponseMiddleware)
        app.include_router(router)
        @app.exception_handler(APIError)
        async def errors(request, error):
            return JSONResponse({"error": error.error}, status_code=error.status_code)
        with TestClient(app) as client:
            headers = {"Origin": "http://localhost:5175"}
            secret = "credential-must-never-appear"
            invalid = client.post("/api/v1/auth/register", headers=headers,
                                  json={"username": "admin", "email": "bad", "password": secret})
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn(secret, invalid.text)
            self.assertEqual(invalid.headers["cache-control"], "no-store")
            invalid = client.post("/api/v1/auth/reset-password", headers=headers,
                                  json={"token": secret * 2, "password": "x"})
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn(secret, invalid.text)
            invalid = client.post("/api/v1/auth/login", headers=headers | {"Content-Type": "application/json"},
                                  content=json.dumps({"username": "Alice", "password": "x" * 15 + "\ud800"}))
            self.assertEqual(invalid.status_code, 422)
            oversized = client.post("/api/v1/auth/login", headers=headers | {"Content-Type": "application/json"},
                                    content=b"x" * 16385)
            self.assertEqual(oversized.status_code, 413)

    def test_mail_worker_success_clears_secret_and_retry_is_bounded(self):
        import smtplib
        from app.auth.mail import MailWorker
        from app.auth.service import db_now
        from app.db.models import AuthMailOutbox
        from sqlalchemy import select
        self.register()
        sent = []
        worker = MailWorker(self.sessions, self.settings, sender=lambda config, payload: sent.append(payload))
        self.assertTrue(worker.run_once())
        self.assertFalse(worker.run_once())
        self.assertEqual(len(sent), 1)
        with self.sessions.begin() as session:
            row = session.scalar(select(AuthMailOutbox))
            self.assertEqual((row.status, row.attempts, row.payload_ciphertext), ("sent", 1, None))
        self.clear_rates()
        self.auth.email_request("alice@example.com", "verify_email", "127.0.0.1", "en")
        def fail(config, payload):
            raise smtplib.SMTPDataError(451, b"fixture secret must not be stored")
        worker = MailWorker(self.sessions, self.settings, sender=fail)
        for attempt in range(3):
            worker.run_once()
            with self.sessions.begin() as session:
                row = session.scalar(select(AuthMailOutbox).where(AuthMailOutbox.status != "sent"))
                self.assertEqual(row.attempts, attempt + 1)
                self.assertNotIn("secret", row.error_code)
                if attempt < 2:
                    self.assertEqual(row.status, "queued")
                    row.next_attempt_at = db_now(session) - timedelta(seconds=1)
                else:
                    self.assertEqual((row.status, row.payload_ciphertext), ("failed", None))

    def test_http_origin_json_csrf_and_cookie_contract(self):
        from fastapi import Depends, FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from app.auth.api import router
        from app.auth.dependencies import require_user
        from app.errors import APIError
        app = FastAPI()
        app.state.sessions, app.state.settings = self.sessions, self.settings
        app.include_router(router)
        @app.exception_handler(APIError)
        async def errors(request, error):
            return JSONResponse({"error": error.error}, status_code=error.status_code, headers=error.headers)
        @app.post("/private")
        def private(user=Depends(require_user)):
            return {"id": str(user.id)}
        self.activate()
        with TestClient(app) as client:
            data = {"username": "Alice", "password": self.password}
            self.assertEqual(client.post("/api/v1/auth/login", json=data).status_code, 403)
            headers = {"Origin": "http://localhost:5175"}
            self.assertEqual(client.post("/api/v1/auth/login", data=data, headers=headers).status_code, 415)
            self.assertEqual(client.post("/api/v1/auth/login", json=data, headers={"Origin": "http://evil.invalid"}).status_code, 403)
            login = client.post("/api/v1/auth/login", json=data, headers=headers)
            self.assertEqual(login.status_code, 200, login.text)
            cookie = login.headers["set-cookie"].lower()
            self.assertIn("httponly", cookie)
            self.assertIn("samesite=lax", cookie)
            self.assertIn("path=/", cookie)
            self.assertEqual(set(login.json()), {"user", "csrf_token"})
            me = client.get("/api/v1/auth/me")
            self.assertEqual(me.json(), login.json())
            self.assertEqual(me.headers["cache-control"], "no-store")
            self.assertEqual(client.post("/private", headers=headers).status_code, 403)
            headers["X-CSRF-Token"] = me.json()["csrf_token"]
            self.assertEqual(client.post("/private", headers=headers).status_code, 200)
            self.assertEqual(client.post("/api/v1/auth/logout", json={}, headers=headers).status_code, 200)
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_mail_worker_reclaims_expired_lease_but_preserves_live_owner(self):
        from app.auth.mail import MailWorker
        from app.auth.service import db_now
        from app.db.models import AuthMailOutbox
        from sqlalchemy import select
        self.register()
        sent = []
        worker = MailWorker(self.sessions, self.settings, sender=lambda config, payload: sent.append(payload))
        with self.sessions.begin() as session:
            row = session.scalar(select(AuthMailOutbox))
            row.status, row.worker_id = "sending", uuid4()
            row.attempts = 1
            row.lease_expires_at = db_now(session) + timedelta(minutes=1)
        self.assertFalse(worker.run_once())
        with self.sessions.begin() as session:
            row = session.scalar(select(AuthMailOutbox))
            row.lease_expires_at = db_now(session) - timedelta(seconds=1)
        self.assertTrue(worker.run_once())
        self.assertEqual(len(sent), 1)
        with self.sessions() as session:
            row = session.scalar(select(AuthMailOutbox))
            self.assertEqual((row.status, row.attempts), ("sent", 2))

    def test_wrong_mail_key_revokes_token_and_discards_payload(self):
        from cryptography.fernet import Fernet
        from app.auth.mail import MailWorker
        from app.db.models import AuthEmailToken, AuthMailOutbox
        from sqlalchemy import select
        self.register()
        bad = settings(mail_outbox_key=SecretStr(Fernet.generate_key().decode()))
        sent = []
        self.assertTrue(MailWorker(self.sessions, bad, sender=lambda *args: sent.append(args)).run_once())
        self.assertEqual(sent, [])
        with self.sessions() as session:
            row = session.scalar(select(AuthMailOutbox))
            self.assertEqual((row.status, row.payload_ciphertext), ("failed", None))
            self.assertIsNotNone(session.scalar(select(AuthEmailToken)).revoked_at)

    def test_missing_mail_key_revokes_queued_tokens_and_fails_closed(self):
        from app.auth.mail import MailWorker
        from app.db.models import AuthEmailToken, AuthMailOutbox
        from app.errors import APIError
        from sqlalchemy import select
        self.register()
        with self.assertRaises(APIError) as caught:
            MailWorker(self.sessions, settings(mail_outbox_key=None), sender=lambda *args: self.fail("Must not send")).run_once()
        self.assertEqual(caught.exception.status_code, 503)
        with self.sessions() as session:
            row = session.scalar(select(AuthMailOutbox))
            self.assertEqual((row.status, row.payload_ciphertext), ("failed", None))
            self.assertIsNotNone(session.scalar(select(AuthEmailToken)).revoked_at)

    def test_mail_worker_permanent_auth_error_never_retries(self):
        import smtplib
        from app.auth.mail import MailWorker
        from app.db.models import AuthMailOutbox
        from sqlalchemy import select
        self.register()
        def denied(config, payload):
            raise smtplib.SMTPAuthenticationError(535, b"private fixture credentials")
        worker = MailWorker(self.sessions, self.settings, sender=denied)
        self.assertTrue(worker.run_once())
        self.assertFalse(worker.run_once())
        with self.sessions() as session:
            row = session.scalar(select(AuthMailOutbox))
            self.assertEqual((row.status, row.attempts, row.payload_ciphertext), ("failed", 1, None))
            self.assertEqual(row.error_code, "SMTP_AUTHENTICATION")

    def test_expired_mail_token_is_never_sent(self):
        from app.auth.mail import MailWorker
        from app.auth.service import db_now
        from app.db.models import AuthEmailToken, AuthMailOutbox
        from sqlalchemy import select
        self.register()
        with self.sessions.begin() as session:
            session.scalar(select(AuthEmailToken)).expires_at = db_now(session) - timedelta(seconds=1)
        worker = MailWorker(self.sessions, self.settings, sender=lambda *args: self.fail("Expired mail must not be sent"))
        self.assertTrue(worker.run_once())
        with self.sessions() as session:
            row = session.scalar(select(AuthMailOutbox))
            self.assertEqual((row.status, row.payload_ciphertext, row.error_code), ("failed", None, "TOKEN_INACTIVE"))

    def test_worker_cannot_acknowledge_a_lease_owned_by_another_worker(self):
        from app.auth.mail import MailWorker
        from app.auth.service import db_now
        from app.db.models import AuthMailOutbox
        from sqlalchemy import select
        self.register()
        other_owner = uuid4()
        def transfer_lease(config, payload):
            with self.sessions.begin() as session:
                row = session.scalar(select(AuthMailOutbox))
                row.worker_id = other_owner
                row.lease_expires_at = db_now(session) + timedelta(minutes=1)
        worker = MailWorker(self.sessions, self.settings, sender=transfer_lease)
        self.assertTrue(worker.run_once())
        with self.sessions() as session:
            row = session.scalar(select(AuthMailOutbox))
            self.assertEqual((row.status, row.worker_id), ("sending", other_owner))
            self.assertIsNotNone(row.payload_ciphertext)

    def test_crash_recovery_never_exceeds_three_delivery_attempts(self):
        from app.auth.mail import MailWorker
        from app.auth.service import db_now
        from app.db.models import AuthMailOutbox
        from sqlalchemy import select
        self.register()
        with self.sessions.begin() as session:
            row = session.scalar(select(AuthMailOutbox))
            row.status, row.attempts, row.worker_id = "sending", 3, uuid4()
            row.lease_expires_at = db_now(session) - timedelta(seconds=1)
        worker = MailWorker(self.sessions, self.settings, sender=lambda *args: self.fail("Attempt budget exhausted"))
        self.assertTrue(worker.run_once())
        self.assertFalse(worker.run_once())
        with self.sessions() as session:
            row = session.scalar(select(AuthMailOutbox))
            self.assertEqual((row.status, row.attempts, row.payload_ciphertext), ("failed", 3, None))

    def test_mail_atomic_rollback_if_encryption_fails(self):
        from unittest.mock import patch
        from sqlalchemy import func, select
        from app.db.models import User, AuthEmailToken, AuthMailOutbox
        with patch("app.auth.service.encrypt_payload", side_effect=ValueError("fixture encryption failure")):
            with self.assertRaises(ValueError):
                self.register()
        with self.sessions() as session:
            for model in (User, AuthEmailToken, AuthMailOutbox):
                self.assertEqual(session.scalar(select(func.count()).select_from(model)), 0)


POSTGRES_URL = os.environ.get("AUTH_TEST_DATABASE_URL")


def isolated_postgres_target(value):
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError
    try:
        target = make_url(value)
        return (target.drivername in {"postgresql", "postgresql+psycopg"}
                and target.host in {"localhost", "127.0.0.1", "::1"}
                and not {key.lower() for key in target.query}.intersection({"host", "hostaddr", "dbname", "service"})
                and bool(re.fullmatch(r"literature_v3_test_auth(?:_[0-9a-f]{32})?", target.database or "")))
    except (ArgumentError, TypeError, ValueError):
        return False


@unittest.skipUnless(POSTGRES_URL, "Set AUTH_TEST_DATABASE_URL to an isolated local literature_v3_test_auth database")
class AuthPostgresTests(AuthBehaviorTests):
    def setUp(self):
        from sqlalchemy import MetaData, create_engine, text
        from sqlalchemy.orm import sessionmaker
        from app.auth.service import AuthService
        from app.db.models import AuthEmailToken, AuthMailOutbox, AuthRateBucket, AuthSession, User
        if not isolated_postgres_target(POSTGRES_URL):
            raise RuntimeError("Refused: authentication tests require the local isolated literature_v3_test_auth database")
        self.models = (User, AuthSession, AuthEmailToken, AuthMailOutbox, AuthRateBucket)
        self.schema = "auth_test_" + uuid4().hex
        self.engine = create_engine(POSTGRES_URL, execution_options={"schema_translate_map": {None: self.schema}})
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as connection:
            version = connection.scalar(text("SELECT version()"))
        native_cases = {
            "test_concurrent_reset_consumes_token_exactly_once",
            "test_concurrent_registration_has_one_username_winner",
            "test_concurrent_login_and_reset_fences_old_password_session",
            "test_skip_locked_mail_claim_never_duplicates_a_live_lease",
            "test_mail_claim_skips_a_row_locked_by_another_transaction",
            "test_concurrent_rate_bucket_updates_do_not_lose_attempts",
            "test_rate_cleanup_preserves_a_concurrently_refreshed_bucket",
        }
        if "PGlite" in version and self._testMethodName in native_cases:
            self.skipTest("Native PostgreSQL required: PGlite serializes transactions")
        with self.engine.begin() as connection:
            connection.execute(text('CREATE SCHEMA "' + self.schema + '"'))
            metadata = MetaData()
            for model in self.models:
                model.__table__.to_metadata(metadata)
            metadata.create_all(connection)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.settings = settings()
        self.auth = AuthService(self.sessions, self.settings)
        self.password = "a long fixture password"

    def tearDown(self):
        from sqlalchemy import text
        with self.engine.begin() as connection:
            connection.execute(text('DROP SCHEMA "' + self.schema + '" CASCADE'))

    def test_mail_claim_skips_a_row_locked_by_another_transaction(self):
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import select
        from app.auth.mail import MailWorker
        from app.db.models import AuthMailOutbox
        self.register()
        delivered = []
        worker = MailWorker(self.sessions, self.settings, sender=lambda *args: delivered.append(True))
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.sessions.begin() as locker:
                self.assertIsNotNone(locker.scalar(select(AuthMailOutbox).with_for_update()))
                self.assertFalse(executor.submit(worker.run_once).result(timeout=3))
                self.assertEqual(delivered, [])
        self.assertTrue(worker.run_once())
        self.assertEqual(delivered, [True])

    def test_concurrent_rate_bucket_updates_do_not_lose_attempts(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from sqlalchemy import select
        from app.db.models import AuthRateBucket
        from app.errors import APIError
        barrier = Barrier(6)
        def attempt(index):
            barrier.wait(timeout=5)
            try:
                self.auth.limits([("fixture", "shared", 2, 900)])
                return 200
            except APIError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=6) as executor:
            self.assertEqual(sorted(executor.map(attempt, range(6))), [200, 200, 429, 429, 429, 429])
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(AuthRateBucket.count)), 6)

    def test_rate_cleanup_preserves_a_concurrently_refreshed_bucket(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import text, update
        from app.auth.service import db_now
        from app.db.models import AuthRateBucket
        from app.errors import APIError
        self.auth.limits([("fixture", "shared", 1, 900)])
        with self.sessions.begin() as session:
            session.execute(update(AuthRateBucket).values(expires_at=db_now(session) - timedelta(seconds=1)))
        def attempt():
            try:
                self.auth.limits([("fixture", "shared", 1, 900)])
                return 200
            except APIError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.sessions.begin() as locker:
                locker.execute(update(AuthRateBucket).values(expires_at=db_now(locker) + timedelta(seconds=900)))
                blocker = locker.scalar(text("SELECT pg_backend_pid()"))
                future = executor.submit(attempt)
                deadline, waiting = time.monotonic() + 3, False
                while time.monotonic() < deadline:
                    with self.engine.connect() as observer:
                        waiting = observer.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                                                       "WHERE :blocker = ANY(pg_blocking_pids(pid)))"),
                                                  {"blocker": blocker})
                    if waiting:
                        break
                    time.sleep(0.01)
                self.assertTrue(waiting, "Competing transaction must reach the held row lock")
            self.assertEqual(future.result(timeout=5), 429)

    def test_concurrent_reset_consumes_token_exactly_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from app.errors import APIError
        self.activate()
        self.clear_rates()
        self.auth.email_request("alice@example.com", "reset_password", "127.0.0.1", "en")
        token = self.latest_token("reset_password")
        barrier = Barrier(2)
        def reset(index):
            barrier.wait(timeout=5)
            try:
                self.auth.reset_password(token, "a different long password", "127.0.0." + str(index + 2))
                return 200
            except APIError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(reset, range(2))), [200, 400])

    def test_concurrent_registration_has_one_username_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from app.errors import APIError
        from app.db.models import User
        from sqlalchemy import func, select
        barrier = Barrier(2)
        def register(index):
            barrier.wait(timeout=5)
            try:
                self.auth.register("Alice", f"alice{index}@example.com", self.password, f"127.0.0.{index + 2}", "en")
                return 202
            except APIError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(register, range(2))), [202, 409])
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 1)

    def test_concurrent_login_and_reset_fences_old_password_session(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from app.errors import APIError
        self.activate()
        self.clear_rates()
        self.auth.email_request("alice@example.com", "reset_password", "127.0.0.1", "en")
        token = self.latest_token("reset_password")
        barrier = Barrier(2)
        def login():
            barrier.wait(timeout=5)
            try:
                return self.auth.login("alice", self.password, "127.0.0.2")[1]
            except APIError as error:
                self.assertEqual(error.status_code, 401)
                return None
        def reset():
            barrier.wait(timeout=5)
            self.auth.reset_password(token, "a different long password", "127.0.0.3")
        with ThreadPoolExecutor(max_workers=2) as executor:
            login_future = executor.submit(login)
            reset_future = executor.submit(reset)
            raw = login_future.result(timeout=10)
            reset_future.result(timeout=10)
        if raw:
            with self.assertRaises(APIError):
                self.auth.authenticate(raw)

    def test_skip_locked_mail_claim_never_duplicates_a_live_lease(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from app.auth.mail import MailWorker
        self.register()
        entered, release = Event(), Event()
        def blocked_sender(config, payload):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Fixture lease test timed out")
        first = MailWorker(self.sessions, self.settings, sender=blocked_sender)
        second = MailWorker(self.sessions, self.settings, sender=lambda *args: self.fail("Lease is already owned"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(first.run_once)
            try:
                self.assertTrue(entered.wait(timeout=5))
                self.assertFalse(second.run_once())
            finally:
                release.set()
            self.assertTrue(future.result(timeout=5))


def run_postgres_tests():
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from app.config import Settings
    admin = None
    created = False
    database = "literature_v3_test_auth_" + uuid4().hex
    try:
        base = make_url(Settings().database_url.get_secret_value())
        target = base.set(database=database)
        if not isolated_postgres_target(target):
            raise RuntimeError("Refused nonlocal PostgreSQL target")
        admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT",
                              connect_args={"connect_timeout": 5})
        with admin.connect() as connection:
            version = connection.scalar(text("SELECT version()"))
            if "PGlite" in version:
                raise RuntimeError("Native PostgreSQL required")
            connection.exec_driver_sql('CREATE DATABASE "' + database + '"')
            created = True
        print("Created isolated database:", database, flush=True)
        print("Native PostgreSQL:", version, flush=True)
        environment = dict(os.environ, AUTH_TEST_DATABASE_URL=target.render_as_string(hide_password=False),
                           PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        return subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "-v"],
                              env=environment, timeout=180).returncode
    except Exception as error:
        print("Native auth harness failed:", type(error).__name__, file=sys.stderr)
        return 1
    finally:
        if admin is not None:
            try:
                if created:
                    with admin.connect() as connection:
                        connection.exec_driver_sql('DROP DATABASE "' + database + '" WITH (FORCE)')
                    print("Dropped isolated database:", database, flush=True)
            finally:
                admin.dispose()


def run_pglite_tests():
    script = r"""
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const packages = process.env.PGLITE_NODE_MODULES || path.join(os.tmpdir(), 'acs-db-design-check-20261110', 'node_modules');
const { PGlite } = require(path.join(packages, '@electric-sql', 'pglite'));
const { PGLiteSocketServer } = require(path.join(packages, '@electric-sql', 'pglite-socket'));
(async () => {
  const database = await PGlite.create();
  const server = new PGLiteSocketServer({ db: database, host: '127.0.0.1', port: 0, maxConnections: 20 });
  try {
    await server.start();
    console.log('Isolated PostgreSQL engine:', (await database.query('SELECT version()')).rows[0].version);
    await new Promise((resolve, reject) => {
      const child = spawn(process.argv[2], ['-B', process.argv[1], '-v'], {
        env: { ...process.env, PYTHONPATH: path.resolve('backend/src'), AUTH_TEST_DATABASE_URL: 'postgresql+psycopg://postgres@' + server.getServerConn() + '/literature_v3_test_auth?sslmode=disable' },
        stdio: 'inherit', windowsHide: true, timeout: 90000,
      });
      child.once('error', reject);
      child.once('exit', code => code === 0 ? resolve() : reject(new Error('Auth tests exited ' + code)));
    });
  } finally {
    await server.stop();
    await database.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
"""
    return subprocess.run(["node", "-e", script, str(Path(__file__).resolve()), sys.executable],
                          cwd=Path(__file__).resolve().parents[2], timeout=110).returncode


if __name__ == "__main__":
    if sys.argv[1:] == ["--postgres"]:
        raise SystemExit(run_postgres_tests())
    if sys.argv[1:] == ["--pglite"]:
        raise SystemExit(run_pglite_tests())
    unittest.main()
