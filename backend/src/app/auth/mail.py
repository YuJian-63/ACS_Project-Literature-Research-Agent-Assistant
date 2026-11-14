import json
import queue
import smtplib
import socket
import ssl
import threading
from datetime import timedelta
from email.message import EmailMessage
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy import and_, or_, select

from app.auth.security import check_config


def make_payload(settings, purpose, recipient, username, token, locale="en", *, ttl_seconds=None) -> dict:
    verify = purpose == "verify_email"
    path = "verify-email" if verify else "reset-password"
    url = settings.frontend_public_url.rstrip("/") + "/" + path + "#token=" + quote(token, safe="")
    seconds = ttl_seconds if ttl_seconds is not None else (
        settings.auth_verify_ttl_seconds if verify else settings.auth_reset_ttl_seconds
    )
    minutes = max(1, (seconds + 59) // 60)
    if locale == "zh":
        subject = "验证邮箱" if verify else "重置密码"
        body = f"你好 {username}，\n\n{subject}：\n{url}\n\n此链接仅可使用一次，将在 {minutes} 分钟后过期。"
        body += "\n如果这不是你的操作，请忽略此邮件。"
        if verify:
            body += "验证邮箱还需要输入注册时设置的密码。"
    else:
        subject = "Verify your email" if verify else "Reset your password"
        body = f"Hello {username},\n\n{subject}:\n{url}\n\nThis single-use link expires in {minutes} minutes."
        body += "\nIf you did not request this, ignore this email. Email verification also requires your signup password."
    return {"to": recipient, "subject": subject, "body": body}


def encrypt_payload(settings, payload) -> str:
    from cryptography.fernet import Fernet
    return Fernet(settings.mail_outbox_key.get_secret_value().encode("ascii")).encrypt(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")


def decrypt_payload(settings, ciphertext) -> dict:
    from cryptography.fernet import Fernet
    return json.loads(Fernet(settings.mail_outbox_key.get_secret_value().encode("ascii")).decrypt(
        ciphertext.encode("ascii")
    ))


def send_payload(settings, payload) -> None:
    check_config(settings, mail=True)
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = payload["to"]
    message["Subject"] = payload["subject"]
    message.set_content(payload["body"])
    result = queue.Queue(maxsize=1)
    cancelled = threading.Event()
    connection = []

    def deliver():
        try:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                 timeout=settings.smtp_timeout_seconds, context=ssl.create_default_context()) as smtp:
                connection.append(smtp)
                if cancelled.is_set():
                    raise TimeoutError("Mail attempt expired")
                smtp.login(settings.smtp_username, settings.smtp_auth_code.get_secret_value())
                if cancelled.is_set():
                    raise TimeoutError("Mail attempt expired")
                smtp.send_message(message)
            result.put(None)
        except Exception as error:
            result.put(error)

    thread = threading.Thread(target=deliver, name="smtp-delivery", daemon=True)
    thread.start()
    try:
        error = result.get(timeout=settings.smtp_timeout_seconds)
    except queue.Empty:
        cancelled.set()
        if connection:
            smtp = connection[0]
            try:
                if smtp.sock:
                    smtp.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            smtp.close()
        raise TimeoutError("Mail attempt expired") from None
    if error:
        raise error


def classify_error(error) -> tuple[str, bool]:
    if isinstance(error, (ssl.SSLCertVerificationError, ssl.CertificateError)):
        return "TLS_CERTIFICATE", False
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return "SMTP_AUTHENTICATION", False
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        retry = bool(error.recipients) and all(400 <= value[0] < 500 for value in error.recipients.values())
        return "SMTP_RECIPIENT", retry
    if isinstance(error, smtplib.SMTPResponseException):
        return "SMTP_RESPONSE", 400 <= error.smtp_code < 500
    if isinstance(error, (OSError, smtplib.SMTPException)):
        return "SMTP_TRANSPORT", True
    return "MAIL_PAYLOAD_INVALID", False


def finish(row, status, error_code=None) -> None:
    row.status = status
    row.error_code = error_code
    row.worker_id = None
    row.lease_expires_at = None
    if status in {"sent", "failed"}:
        row.payload_ciphertext = None


class MailWorker:
    def __init__(self, sessions, settings, *, sender=send_payload):
        self.sessions = sessions
        self.settings = settings
        self.sender = sender
        self.worker_id = uuid4()

    def run_once(self) -> bool:
        from app.auth.service import db_now, usable_token
        from app.db.models import AuthEmailToken, AuthMailOutbox, User
        try:
            from cryptography.fernet import Fernet
            Fernet(self.settings.mail_outbox_key.get_secret_value().encode("ascii"))
        except ImportError:
            from app.auth.security import unavailable
            raise unavailable() from None
        except (AttributeError, TypeError, ValueError, UnicodeError):
            self.discard_unreadable()
        check_config(self.settings, mail=True)
        with self.sessions.begin() as session:
            now = db_now(session)
            row = session.scalar(select(AuthMailOutbox).where(or_(
                and_(AuthMailOutbox.status == "queued", AuthMailOutbox.next_attempt_at <= now),
                and_(AuthMailOutbox.status == "sending", AuthMailOutbox.lease_expires_at <= now),
            )).order_by(AuthMailOutbox.next_attempt_at, AuthMailOutbox.id).with_for_update(skip_locked=True).limit(1))
            if row is None:
                return False
            if row.attempts >= 3:
                finish(row, "failed", "ATTEMPTS_EXHAUSTED")
                row.updated_at = now
                return True
            row.status = "sending"
            row.attempts += 1
            row.worker_id = self.worker_id
            row.lease_expires_at = now + timedelta(seconds=10 * self.settings.smtp_timeout_seconds + 60)
            row.updated_at = now
            row_id, user_id, token_id = row.id, row.user_id, row.token_id
        payload = None
        with self.sessions.begin() as session:
            user = session.scalar(select(User).where(User.id == user_id).with_for_update())
            token = session.scalar(select(AuthEmailToken).where(AuthEmailToken.id == token_id).with_for_update())
            row = session.scalar(select(AuthMailOutbox).where(AuthMailOutbox.id == row_id).with_for_update())
            now = db_now(session)
            if not self.owns(row, now):
                return True
            expected = "pending" if token and token.purpose == "verify_email" else "active"
            if (not user or user.status != expected or not token or token.user_id != user.id
                    or not usable_token(token, now)):
                finish(row, "failed", "TOKEN_INACTIVE")
            else:
                try:
                    payload = decrypt_payload(self.settings, row.payload_ciphertext)
                    if set(payload) != {"to", "subject", "body"} or payload["to"] != user.email:
                        raise ValueError("Invalid payload")
                except Exception:
                    finish(row, "failed", "MAIL_KEY_OR_PAYLOAD_INVALID")
                    token.revoked_at = now
                    payload = None
            row.updated_at = now
        if payload is None:
            return True
        error_code, retryable = None, False
        try:
            self.sender(self.settings, payload)
        except Exception as error:
            error_code, retryable = classify_error(error)
        with self.sessions.begin() as session:
            row = session.scalar(select(AuthMailOutbox).where(AuthMailOutbox.id == row_id).with_for_update())
            now = db_now(session)
            if not self.owns(row, now):
                return True
            if error_code is None:
                finish(row, "sent")
            else:
                delay = 30 if row.attempts == 1 else 120
                token = session.get(AuthEmailToken, token_id)
                if retryable and row.attempts < 3 and token and usable_token(token, now + timedelta(seconds=delay)):
                    finish(row, "queued", error_code)
                    row.next_attempt_at = now + timedelta(seconds=delay)
                else:
                    finish(row, "failed", error_code)
            row.updated_at = now
        return True

    def owns(self, row, now) -> bool:
        from app.auth.service import aware
        return bool(row and row.status == "sending" and row.worker_id == self.worker_id
                    and row.lease_expires_at and aware(row.lease_expires_at) > now)

    def discard_unreadable(self):
        from app.auth.security import unavailable
        from app.auth.service import AuthService, db_now
        from app.db.models import AuthMailOutbox, User
        with self.sessions.begin() as session:
            user_ids = select(AuthMailOutbox.user_id).where(AuthMailOutbox.status.in_(["queued", "sending"]))
            users = session.scalars(select(User).where(User.id.in_(user_ids)).order_by(User.id)
                                    .with_for_update(skip_locked=True).limit(100)).all()
            for user in users:
                AuthService(self.sessions, self.settings).revoke_tokens(session, user.id, db_now(session))
        raise unavailable()
