import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.sources.arxiv import ArxivError, ArxivPaper, DownloadReceipt, MAX_PDF_BYTES, normalize_arxiv_id
from app.db.models import Paper, PaperImport, PaperSource
from app.errors import APIError
from app.papers.storage import controlled_path

logger = logging.getLogger(__name__)
LEASE_SECONDS = 30
HEARTBEAT_SECONDS = 10
ATTEMPT_SECONDS = 180


@dataclass(frozen=True)
class ImportJob:
    import_id: UUID
    provider: str
    external_id: str
    attempt: int
    worker_id: UUID
    started_at: datetime
    deadline: datetime


class ImportCommitPending(Exception):
    pass


def owns_import(item: PaperImport | None, job: ImportJob, now: datetime) -> bool:
    return bool(item is not None and item.status == "running" and item.worker_id == job.worker_id
                and item.attempt == job.attempt and item.lease_expires_at > now
                and item.started_at + timedelta(seconds=ATTEMPT_SECONDS) > now)


def staging_path(root: Path, job: ImportJob) -> Path:
    root = root.resolve()
    path = root / "import-temp" / f"{job.import_id}-{job.attempt}-{job.worker_id}.part"
    if path.resolve() != path:
        raise ArxivError("STORAGE_WRITE_FAILED", "导入临时路径不安全", retryable=True)
    return path


def claim_import(sessions: sessionmaker[Session], worker_id: UUID) -> ImportJob | None:
    with sessions.begin() as session:
        item = session.scalar(select(PaperImport).where(PaperImport.status == "queued")
                              .order_by(PaperImport.created_at, PaperImport.id).limit(1).with_for_update(skip_locked=True))
        if item is None:
            return None
        now = session.scalar(select(func.clock_timestamp()))
        item.status = "running"
        item.worker_id = worker_id
        item.started_at = item.updated_at = now
        item.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        return ImportJob(item.id, item.provider, item.external_id, item.attempt, worker_id, now, now + timedelta(seconds=ATTEMPT_SECONDS))


def heartbeat_import(sessions: sessionmaker[Session], job: ImportJob) -> bool:
    with sessions.begin() as session:
        item = session.scalar(select(PaperImport).where(PaperImport.id == job.import_id).with_for_update())
        now = session.scalar(select(func.clock_timestamp()))
        if not owns_import(item, job, now):
            return False
        item.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        item.updated_at = now
        return True


def mark_import_failed(item: PaperImport, now: datetime, code: str, message: str, retryable: bool) -> None:
    item.status = "failed"
    item.worker_id = item.lease_expires_at = None
    item.finished_at = item.updated_at = now
    item.error_code = code
    item.error_message = message
    item.error_details = {"retryable": retryable}


def fail_import(sessions: sessionmaker[Session], job: ImportJob, code: str, message: str, retryable: bool) -> bool:
    if type(retryable) is not bool:
        raise ValueError("Retryable must be boolean")
    with sessions.begin() as session:
        item = session.scalar(select(PaperImport).where(PaperImport.id == job.import_id).with_for_update())
        now = session.scalar(select(func.clock_timestamp()))
        if not owns_import(item, job, now):
            return False
        mark_import_failed(item, now, code, message, retryable)
        return True


def recover_imports(sessions: sessionmaker[Session], *, root: Path | None = None) -> int:
    with sessions.begin() as session:
        items = list(session.scalars(select(PaperImport).where(PaperImport.status == "running", or_(
            PaperImport.lease_expires_at <= func.clock_timestamp(),
            PaperImport.started_at <= func.clock_timestamp() - timedelta(seconds=ATTEMPT_SECONDS),
        )).order_by(PaperImport.id).limit(100).with_for_update(skip_locked=True)))
        now = session.scalar(select(func.clock_timestamp()))
        for item in items:
            if root is not None and session.get(Paper, item.id) is None:
                final = controlled_path(root, item.id, f"uploads/{item.id}.pdf")
                final.unlink(missing_ok=True)
            timed_out = item.started_at + timedelta(seconds=ATTEMPT_SECONDS) <= now
            mark_import_failed(item, now, "IMPORT_TIMEOUT" if timed_out else "IMPORT_LEASE_EXPIRED",
                               "导入执行超时" if timed_out else "导入 Worker 租约已过期", True)
        return len(items)


def complete_import(
    sessions: sessionmaker[Session], job: ImportJob, metadata: ArxivPaper, receipt: DownloadReceipt,
    *, root: Path,
) -> bool:
    metadata = ArxivPaper.model_validate(metadata.model_dump())
    if metadata.external_id != job.external_id or metadata.provider != job.provider:
        raise ArxivError("ARXIV_VERSION_MISMATCH", "返回的论文版本与请求不一致")
    staged = staging_path(root, job)
    digest = hashlib.sha256()
    size = 0
    header = b""
    with staged.open("rb") as source:
        while chunk := source.read(64 * 1024):
            size += len(chunk)
            if size > MAX_PDF_BYTES:
                raise ArxivError("FILE_TOO_LARGE", "论文文件最大为 20 MiB")
            header = (header + chunk)[:5]
            digest.update(chunk)
    if header != b"%PDF-" or size != receipt.size_bytes or digest.hexdigest() != receipt.sha256:
        raise ArxivError("INVALID_PDF", "导入文件与已下载内容不一致")
    final = controlled_path(root, job.import_id, f"uploads/{job.import_id}.pdf")
    moved = False
    session = sessions()
    try:
        item = session.scalar(select(PaperImport).where(PaperImport.id == job.import_id).with_for_update())
        now = session.scalar(select(func.clock_timestamp()))
        if not owns_import(item, job, now):
            session.rollback()
            return False
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists() or final.is_symlink():
            raise ImportCommitPending("Final PDF requires reconciliation")
        with final.open("xb") as destination, staged.open("rb") as source:
            moved = True
            while chunk := source.read(64 * 1024):
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        now = session.scalar(select(func.clock_timestamp()))
        if not owns_import(item, job, now):
            raise ArxivError("IMPORT_TIMEOUT", "导入执行时限已到", retryable=True)
        session.add(Paper(id=job.import_id, title=metadata.title[:255], original_filename=job.external_id.replace("/", "_") + ".pdf",
                          storage_key=f"uploads/{job.import_id}.pdf", size_bytes=size, sha256=receipt.sha256,
                          status="uploaded", created_at=now, updated_at=now))
        session.flush()
        session.add(PaperSource(paper_id=job.import_id, provider=job.provider, external_id=job.external_id,
                                source_metadata=metadata.model_dump(mode="json", exclude={"provider", "external_id"}), created_at=now))
        item.status = "succeeded"
        item.paper_id = job.import_id
        item.worker_id = item.lease_expires_at = None
        item.finished_at = item.updated_at = now
        session.flush()
    except Exception:
        session.rollback()
        session.close()
        if moved:
            try:
                with sessions.begin() as lookup:
                    current = lookup.scalar(select(PaperImport).where(PaperImport.id == job.import_id).with_for_update())
                    if (current is not None and current.attempt == job.attempt and current.status != "succeeded"
                            and current.worker_id in {None, job.worker_id} and lookup.get(Paper, job.import_id) is None):
                        final.unlink(missing_ok=True)
            except (SQLAlchemyError, OSError):
                logger.warning("Import file cleanup deferred: import_id=%s", job.import_id)
        raise
    try:
        session.commit()
    except SQLAlchemyError:
        session.close()
        try:
            with sessions() as lookup:
                item = lookup.scalar(select(PaperImport).where(PaperImport.id == job.import_id).with_for_update())
                paper = lookup.get(Paper, job.import_id)
                if item is not None and item.status == "succeeded" and paper is not None and paper.sha256 == receipt.sha256 and paper.source is not None:
                    return True
                if paper is None and item is not None and item.attempt == job.attempt:
                    final.unlink(missing_ok=True)
                    raise ArxivError("STORAGE_WRITE_FAILED", "导入结果未提交，可重新尝试", retryable=True)
        except SQLAlchemyError:
            pass
        raise ImportCommitPending("Import commit requires reconciliation") from None
    finally:
        session.close()
    return True


def import_view(session: Session, item: PaperImport) -> dict:
    paper = session.get(Paper, item.paper_id) if item.paper_id is not None else None
    fields = ("id", "provider", "external_id", "attempt", "status", "paper_id", "created_at", "updated_at", "started_at", "finished_at")
    return {
        **{name: getattr(item, name) for name in fields},
        "paper_status": paper.status if paper else None,
        "error": {"code": item.error_code, "message": item.error_message, "details": item.error_details} if item.error_code else None,
    }


def get_import(sessions: sessionmaker[Session], import_id: UUID) -> dict:
    with sessions() as session:
        item = session.get(PaperImport, import_id)
        if item is None:
            raise APIError(404, "PAPER_IMPORT_NOT_FOUND", "导入记录不存在")
        return import_view(session, item)


def submit_import(sessions: sessionmaker[Session], provider: str, external_id: str) -> dict:
    if provider != "arxiv":
        raise ValueError("Unsupported provider")
    external_id = normalize_arxiv_id(external_id)
    try:
        with sessions.begin() as session:
            existing = session.scalar(select(PaperImport).where(PaperImport.provider == provider, PaperImport.external_id == external_id))
            if existing is not None:
                return import_view(session, existing)
            now = session.scalar(select(func.clock_timestamp()))
            item = PaperImport(id=uuid4(), provider=provider, external_id=external_id, created_at=now, updated_at=now)
            session.add(item)
            session.flush()
            result = import_view(session, item)
        return result
    except IntegrityError:
        with sessions() as session:
            existing = session.scalar(select(PaperImport).where(PaperImport.provider == provider, PaperImport.external_id == external_id))
            if existing is None:
                raise
            return import_view(session, existing)


def retry_import(sessions: sessionmaker[Session], import_id: UUID, expected_attempt: int) -> dict:
    if type(expected_attempt) is not int or expected_attempt < 1:
        raise ValueError("Invalid expected attempt")
    with sessions.begin() as session:
        item = session.scalar(select(PaperImport).where(PaperImport.id == import_id).with_for_update())
        if item is None:
            raise APIError(404, "PAPER_IMPORT_NOT_FOUND", "导入记录不存在")
        if item.attempt == expected_attempt + 1:
            return import_view(session, item)
        if item.attempt != expected_attempt or item.status != "failed":
            raise APIError(409, "IMPORT_RETRY_CONFLICT", "导入状态或尝试版本已变化，请刷新")
        if not item.error_details or item.error_details.get("retryable") is not True:
            raise APIError(409, "IMPORT_NOT_RETRYABLE", "此次失败不支持重新下载")
        item.attempt += 1
        item.status = "queued"
        item.started_at = item.finished_at = item.worker_id = item.lease_expires_at = None
        item.error_code = item.error_message = item.error_details = None
        item.updated_at = session.scalar(select(func.clock_timestamp()))
        session.flush()
        return import_view(session, item)
