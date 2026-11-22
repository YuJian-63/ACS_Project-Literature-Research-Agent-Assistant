from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import require_user
from app.db.models import Task, TaskEvaluation, User
from app.errors import APIError
from app.evaluations.service import enqueue_evaluation
from app.tasks.service import get_task

router = APIRouter(prefix="/api/v1/tasks/{task_id}/evaluation")
CurrentUser = Annotated[User, Depends(require_user)]


class EvaluationResponse(BaseModel):
    task_id: UUID
    id: UUID | None = None
    enabled: bool
    configured: bool
    status: Literal["not_requested", "pending", "running", "succeeded", "failed", "skipped"]
    provider: str | None = None
    model: str | None = None
    rubric_version: str | None = None
    prompt_version: str | None = None
    input_sha256: str | None = None
    evidence_sha256: str | None = None
    attempts: int = 0
    max_attempts: int | None = None
    error_code: str | None = None
    report: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    next_attempt_at: datetime | None = None


def evaluation_view(task_id, row, settings) -> dict:
    view = {"task_id": task_id, "enabled": settings.evaluation_enabled,
        "configured": settings.evaluation_configured, "status": "not_requested"}
    if row:
        view.update({name: getattr(row, name) for name in ("id", "status", "input_sha256", "evidence_sha256",
            "attempts", "error_code", "report", "usage", "created_at", "updated_at", "finished_at", "next_attempt_at")})
        view.update({name: row.config[name] for name in ("provider", "model", "rubric_version", "prompt_version", "max_attempts")})
    return view


@router.get("", response_model=EvaluationResponse)
def get_evaluation(task_id: UUID, request: Request, user: CurrentUser, evaluation_id: UUID | None = None):
    with request.app.state.sessions() as session:
        get_task(session, task_id, user.id)
        query = select(TaskEvaluation).where(TaskEvaluation.task_id == task_id)
        if evaluation_id:
            query = query.where(TaskEvaluation.id == evaluation_id)
        row = session.scalar(query.order_by(TaskEvaluation.created_at.desc(), TaskEvaluation.id.desc()).limit(1))
        if evaluation_id and row is None:
            raise APIError(404, "EVALUATION_NOT_FOUND", "Evaluation not found")
        return evaluation_view(task_id, row, request.app.state.settings)


@router.post("", status_code=202, response_model=EvaluationResponse)
def request_evaluation(task_id: UUID, request: Request, user: CurrentUser):
    settings = request.app.state.settings
    with request.app.state.sessions.begin() as session:
        task = session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user.id).with_for_update())
        if task is None:
            raise APIError(404, "TASK_NOT_FOUND", "Research task not found")
        if not settings.evaluation_configured:
            raise APIError(503, "EVALUATION_NOT_CONFIGURED", "Evaluation is disabled or not configured")
        row = enqueue_evaluation(session, task, settings)
        return evaluation_view(task_id, row, settings)
