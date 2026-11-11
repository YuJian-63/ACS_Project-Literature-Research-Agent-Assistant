from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Paper, PaperChunk
from app.lifecycle import LEASE_SECONDS, database_time
from app.pdf_parser import ParseResult


def owns_parse(paper: Paper | None, owner: UUID, now: datetime) -> bool:
    return (paper is not None and paper.status == "processing" and paper.parse_worker_id == owner
            and paper.parse_lease_expires_at > now)


def lock_paper(session: Session, paper_id: UUID) -> Paper | None:
    return session.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())


def claim_parse(sessions: sessionmaker[Session], owner: UUID) -> UUID | None:
    with sessions.begin() as session:
        paper = session.scalar(select(Paper).where(Paper.status == "uploaded")
                               .order_by(Paper.created_at, Paper.id).limit(1).with_for_update(skip_locked=True))
        if paper is None:
            return None
        now = database_time(session)
        paper.status = "processing"
        paper.parse_worker_id = owner
        paper.parse_lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        paper.updated_at = now
        return paper.id


def renew_parse(sessions: sessionmaker[Session], paper_id: UUID, owner: UUID) -> bool:
    with sessions.begin() as session:
        paper = lock_paper(session, paper_id)
        now = database_time(session)
        if not owns_parse(paper, owner, now):
            return False
        paper.parse_lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        paper.updated_at = now
        return True


def mark_parse_failed(paper: Paper, now: datetime, code: str, message: str) -> None:
    paper.status = "failed"
    paper.parse_worker_id = None
    paper.parse_lease_expires_at = None
    paper.updated_at = now
    paper.error_code = code
    paper.error_message = message
    paper.error_details = {}


def fail_parse(sessions: sessionmaker[Session], paper_id: UUID, owner: UUID, code: str, message: str) -> bool:
    with sessions.begin() as session:
        paper = lock_paper(session, paper_id)
        now = database_time(session)
        if not owns_parse(paper, owner, now):
            return False
        mark_parse_failed(paper, now, code, message)
        return True


def finish_parse(sessions: sessionmaker[Session], paper_id: UUID, owner: UUID, source_hash: str, result: ParseResult) -> bool:
    result = ParseResult.model_validate(result.model_dump())
    with sessions.begin() as session:
        paper = lock_paper(session, paper_id)
        now = database_time(session)
        if not owns_parse(paper, owner, now):
            return False
        if paper.sha256 != source_hash or session.scalar(select(PaperChunk.id).where(PaperChunk.paper_id == paper_id).limit(1)):
            raise ValueError("Source changed or evidence already exists")
        session.add_all([PaperChunk(paper_id=paper_id, parser_version=result.parser_version, **chunk.model_dump()) for chunk in result.chunks])
        paper.page_count = result.page_count
        paper.parser_version = result.parser_version
        paper.status = "ready"
        paper.parse_worker_id = None
        paper.parse_lease_expires_at = None
        paper.updated_at = now
        return True


def reap_parses(sessions: sessionmaker[Session]) -> int:
    with sessions.begin() as session:
        papers = list(session.scalars(select(Paper).where(Paper.status == "processing", Paper.parse_lease_expires_at <= func.clock_timestamp())
                                      .order_by(Paper.id).limit(100).with_for_update(skip_locked=True)))
        now = database_time(session)
        for paper in papers:
            mark_parse_failed(paper, now, "PARSER_LOST", "解析 Worker 租约已过期，请重新上传以重试")
        return len(papers)
