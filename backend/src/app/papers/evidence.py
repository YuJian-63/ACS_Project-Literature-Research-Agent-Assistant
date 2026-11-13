from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Paper, PaperChunk
from app.errors import APIError


def read_evidence(sessions: sessionmaker[Session], paper_id: UUID, *, after_index: int = -1, limit: int = 100) -> dict:
    if type(after_index) is not int or after_index < -1 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid evidence cursor or limit")
    with sessions() as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            raise APIError(404, "PAPER_NOT_FOUND", "论文不存在")
        if paper.status != "ready":
            raise APIError(409, "PAPER_NOT_READY", "论文尚未完成解析")
        rows = list(session.scalars(select(PaperChunk).where(PaperChunk.paper_id == paper_id, PaperChunk.chunk_index > after_index)
                                   .order_by(PaperChunk.chunk_index).limit(limit + 1)))
        items = [{"chunk_id": str(chunk.id), "paper_id": str(paper_id), "chunk_index": chunk.chunk_index,
                  "page_number": chunk.page_number, "content": chunk.content, "content_sha256": chunk.content_sha256,
                  "parser_version": chunk.parser_version} for chunk in rows[:limit]]
        return {"paper_id": str(paper_id), "paper_sha256": paper.sha256, "page_count": paper.page_count,
                "parser_version": paper.parser_version, "items": items, "has_more": len(rows) > limit,
                "next_after_index": items[-1]["chunk_index"] if items else after_index}
