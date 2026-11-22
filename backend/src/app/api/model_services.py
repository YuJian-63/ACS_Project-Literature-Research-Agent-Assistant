from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import delete
from dotenv import dotenv_values
from fastapi import APIRouter, Depends, Request

from app.agent_bridge.contracts import validate_course_url
from app.auth.dependencies import require_user
from app.db.models import CourseService, SharedModelEndpoint, User
from app.errors import APIError

router = APIRouter(prefix="/api/v1/models")
CurrentUser = Annotated[User, Depends(require_user)]


def enabled(settings):
    return settings.task_runner == "agent" and settings.agent_transport == "tcloud" and settings.agent_dispatch_enabled


@router.get("")
def models(request: Request, user: CurrentUser):
    settings = request.app.state.settings
    with request.app.state.sessions() as session:
        service = session.get(CourseService, 1)
        model_file = settings.agent_tcloud_model_env_file
        config = dotenv_values(model_file, interpolate=False) if model_file and model_file.is_file() else {}
        shared = session.get(SharedModelEndpoint, user.id)
        return {"shared_url": shared.base_url if shared else None, "generation": service.generation, "bailian_name": config.get("MODEL_NAME") or ("qwen3.8-27b" if config else None),
                "bailian_config": ("local" if config.get("BAILIAN_API_KEY") and config.get("MODEL_BASE_URL") else "missing") if model_file else "remote",
                "enabled": enabled(settings), "state": "stopping" if service.stop_requested else service.state,
                "job_id": service.job_id, "base_url": service.base_url if not service.stop_requested else None,
                "requested_at": service.requested_at, "checked_at": service.checked_at,
                "detail": service.detail, "owner": user.id == service.owner_id}


@router.post("/tacc/{action}", status_code=202)
def change_service(action: Literal["start", "stop"], request: Request, user: CurrentUser, generation: UUID | None = None):
    if not enabled(request.app.state.settings):
        raise APIError(409, "TCLOUD_DISABLED", "课程 TCloud Worker 尚未启用")
    with request.app.state.sessions.begin() as session:
        service = session.get(CourseService, 1, with_for_update=True)
        if action == "start" and service.state in {"stopped", "failed"}:
            service.owner_id, service.generation = user.id, uuid4()
            service.state, service.stop_requested = "requested", False
            service.base_url = service.job_id = service.detail = service.checked_at = None
            service.requested_at = datetime.now(UTC)
        elif action == "stop" and service.state not in {"stopped", "failed"}:
            if service.generation != generation:
                raise APIError(409, "MODEL_SERVICE_CHANGED", "模型服务已更新，请刷新后重试")
            if user.id != service.owner_id:
                raise APIError(403, "MODEL_OWNER_REQUIRED", "只有本轮服务的启动者可以停止作业")
            service.stop_requested = True
    return {"accepted": True}


class SharedEndpointInput(BaseModel):
    base_url: str = Field(max_length=128)

    @field_validator("base_url")
    @classmethod
    def validate_course_url(cls, value):
        return validate_course_url(value)


@router.put("/shared")
def save_shared(body: SharedEndpointInput, request: Request, user: CurrentUser):
    with request.app.state.sessions.begin() as session:
        stmt = insert(SharedModelEndpoint).values(user_id=user.id, base_url=body.base_url)
        session.execute(stmt.on_conflict_do_update(index_elements=["user_id"], set_={"base_url": body.base_url}))
    return {"base_url": body.base_url}


@router.delete("/shared", status_code=204)
def remove_shared(request: Request, user: CurrentUser):
    with request.app.state.sessions.begin() as session:
        session.execute(delete(SharedModelEndpoint).where(SharedModelEndpoint.user_id == user.id))
