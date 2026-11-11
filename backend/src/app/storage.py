import hashlib
import logging
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Paper
from app.errors import APIError
from app.views import paper_view

MAX_FILE_BYTES = 20 * 1024 * 1024
logger = logging.getLogger(__name__)


def validate_filename(filename: str | None) -> tuple[str, str]:
    if (
        not filename or len(filename) > 255 or any(character in filename for character in "/\\")
        or any(unicodedata.category(character).startswith("C") for character in filename)
    ):
        raise APIError(422, "INVALID_FILENAME", "文件名不合法")
    if not filename.lower().endswith(".pdf"):
        raise APIError(422, "INVALID_FILENAME", "文件名必须以 .pdf 结尾")
    title = filename[:-4].strip()
    if not title:
        raise APIError(422, "INVALID_FILENAME", "论文标题不能为空")
    return filename, title


def controlled_path(root: Path, paper_id: UUID, storage_key: str) -> Path:
    expected = f"uploads/{paper_id}.pdf"
    if storage_key != expected:
        raise ValueError("Invalid storage key")
    root = root.resolve()
    target = root / "uploads" / f"{paper_id}.pdf"
    if target.resolve() != target:
        raise ValueError("Storage path escapes controlled location")
    return target


def remove_file(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Upload cleanup deferred")


def save_paper(
    sessions: sessionmaker[Session], root: Path, source: BinaryIO, filename: str | None
) -> dict:
    filename, title = validate_filename(filename)
    paper_id = uuid4()
    storage_key = f"uploads/{paper_id}.pdf"
    temporary = None
    final = None
    try:
        root = root.resolve()
        uploads = root / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        final = controlled_path(root, paper_id, storage_key)
        digest = hashlib.sha256()
        size = 0
        header = b""
        descriptor, temporary_name = tempfile.mkstemp(prefix=f"{paper_id}-", suffix=".part", dir=uploads)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as destination:
            while chunk := source.read(64 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise APIError(413, "FILE_TOO_LARGE", "文件最大为 20 MiB")
                header = (header + chunk[:5])[:5]
                digest.update(chunk)
                destination.write(chunk)
            if header != b"%PDF-":
                raise APIError(422, "INVALID_PDF", "文件为空或缺少 PDF 文件头")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, final)
    except APIError:
        remove_file(temporary)
        raise
    except (OSError, ValueError):
        remove_file(temporary)
        raise APIError(500, "STORAGE_WRITE_FAILED", "文件写入失败") from None

    paper = Paper(
        id=paper_id, title=title, original_filename=filename, storage_key=storage_key,
        size_bytes=size, sha256=digest.hexdigest(),
    )
    with sessions() as session:
        try:
            session.add(paper)
            session.flush()
            result = paper_view(paper)
        except Exception:
            remove_file(final)
            raise
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            remove_file(final)
            raise
        except SQLAlchemyError:
            logger.warning("Upload commit requires reconciliation: paper_id=%s", paper_id)
            try:
                session.close()
            except SQLAlchemyError:
                pass
            try:
                with sessions() as lookup:
                    existing = lookup.get(Paper, paper_id)
                    if (
                        existing is not None and existing.storage_key == storage_key
                        and existing.sha256 == digest.hexdigest()
                    ):
                        return paper_view(existing)
            except SQLAlchemyError:
                pass
            raise APIError(503, "SERVICE_NOT_READY", "上传提交结果待确认，请稍后查询论文列表") from None
    return result
