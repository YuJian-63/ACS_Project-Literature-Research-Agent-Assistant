"""Unified v3 records; execution will be connected to the Agent separately."""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from app.auth.dependencies import require_user
from app.api.pagination import Limit, Offset
from app.api.schemas import TaskStatus
from app.api.agent_research_schemas import AgentResearchCreate
from app.db.models import AgentResearch, ResearchPaper, Paper, User
from app.errors import APIError
router = APIRouter(prefix="/api/v1/agent-research")
CurrentUser = Annotated[User, Depends(require_user)]

def references(session, ids):
    result = {identifier: [] for identifier in ids}
    if ids:
        query = select(ResearchPaper.research_id, Paper.id, Paper.title).join(Paper, (Paper.id == ResearchPaper.paper_id) & (Paper.user_id == ResearchPaper.user_id)).where(ResearchPaper.research_id.in_(ids)).order_by(ResearchPaper.selection_order)
        for research_id, paper_id, title in session.execute(query):
            result[research_id].append({"id": paper_id, "title": title})
    return result

@router.get("")
def list_records(request: Request, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, status: TaskStatus | None = None):
    filters = [AgentResearch.user_id == user.id]
    if status is not None: filters.append(AgentResearch.status == status)
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(AgentResearch).where(*filters))
        rows = list(session.scalars(select(AgentResearch).where(*filters).order_by(AgentResearch.created_at.desc(), AgentResearch.id.desc()).limit(limit).offset(offset)))
        papers = references(session, [row.id for row in rows])
        items = [{"id": row.id, "question": row.question, "status": row.status, "paper_ids": [p["id"] for p in papers[row.id]], "papers": papers[row.id], "created_at": row.created_at} for row in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

@router.get("/{task_id}")
def get_record(task_id: UUID, request: Request, user: CurrentUser):
    with request.app.state.sessions() as session:
        row = session.scalar(select(AgentResearch).where(AgentResearch.id == task_id, AgentResearch.user_id == user.id))
        if row is None: raise APIError(404, "TASK_NOT_FOUND", "研究记录不存在")
        papers = references(session, [row.id])[row.id]
        return {"task_id": row.id, "question": row.question, "status": row.status, "paper_ids": [p["id"] for p in papers], "result": row.result, "error": row.error}

@router.post("")
def create_record(body: AgentResearchCreate, user: CurrentUser):
    raise APIError(503, "AGENT_NOT_CONNECTED", "研究服务暂未连接，请稍后再试。")

@router.delete("/{task_id}", status_code=204)
def delete_record(task_id: UUID, request: Request, user: CurrentUser):
    with request.app.state.sessions.begin() as session:
        row = session.scalar(select(AgentResearch).where(AgentResearch.id == task_id, AgentResearch.user_id == user.id).with_for_update())
        if row is None: raise APIError(404, "TASK_NOT_FOUND", "研究记录不存在")
        if row.status == "running": raise APIError(409, "TASK_RUNNING", "研究正在执行，请等待完成后再删除")
        session.delete(row)
    return Response(status_code=204)
