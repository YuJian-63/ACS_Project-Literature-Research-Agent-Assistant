from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, select

from app.agent_bridge.results import normalize_citation_references
from app.api.pagination import Limit, Offset
from app.api.schemas import (
    ArtifactList,
    EventPage,
    NativeAgentResponse,
    Page,
    TaskAccepted,
    TaskCreate,
    TaskResponse,
    TaskStatus,
    TaskSummary,
    TaskType,
    WorkflowType,
)
from app.api.views import summary_view, task_view
from app.auth.dependencies import require_user
from app.db.models import AgentRun, Artifact, Citation, Paper, Task, TaskEvent, User
from app.errors import APIError
from app.tasks.service import get_task, selected_papers, submit_task

CurrentUser = Annotated[User, Depends(require_user)]

router = APIRouter()


@router.post("/api/v1/tasks", status_code=202, response_model=TaskAccepted)
def create_task(
    request: Request, body: TaskCreate, response: Response, user: CurrentUser,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict:
    if len(request.headers.getlist("idempotency-key")) > 1:
        raise APIError(422, "INVALID_REQUEST", "Idempotency-Key 不能重复")
    result, replayed = submit_task(request.app.state.sessions, request.app.state.settings, body, idempotency_key, user_id=user.id)
    response.headers["Location"] = f"/api/v1/tasks/{result['id']}"
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@router.get("/api/v1/tasks", response_model=Page[TaskSummary])
def list_tasks(
    request: Request, user: CurrentUser, limit: Limit = 20, offset: Offset = 0,
    status: TaskStatus | None = None, task_type: TaskType | None = None,
    workflow_type: WorkflowType | None = None, is_mock: Literal["true", "false"] | None = None,
) -> dict:
    conditions = [Task.user_id == user.id]
    for column, value in ((Task.status, status), (Task.task_type, task_type), (Task.workflow_type, workflow_type)):
        if value is not None:
            conditions.append(column == value)
    if is_mock is not None:
        conditions.append(Task.runner_type == "mock" if is_mock == "true" else Task.runner_type != "mock")
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(Task).where(*conditions))
        tasks = list(session.scalars(
            select(Task).where(*conditions).order_by(Task.created_at.desc(), Task.id.desc()).offset(offset).limit(limit)
        ))
        papers = selected_papers(session, [task.id for task in tasks])
        return {
            "items": [summary_view(task, papers[task.id]) for task in tasks],
            "total": total, "limit": limit, "offset": offset,
        }


@router.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
def task_detail(request: Request, task_id: UUID, user: CurrentUser) -> dict:
    with request.app.state.sessions() as session:
        task = get_task(session, task_id, user.id)
        view = task_view(task, selected_papers(session, [task_id])[task_id])
        if task.runner_type == "agent":
            run = session.get(AgentRun, task_id)
            if run is not None:
                view["agent"] = {"dispatch_id": run.dispatch_id, "remote_job_id": run.remote_job_id,
                    "transport": task.run_config.get("transport", "file-exchange-v1"),
                    "stop_reason": run.stop_reason, "unresolved": (run.result or {}).get("unresolved", []),
                    "limits": task.run_config["agent_limits"]}
        return view


@router.get("/api/v1/tasks/{task_id}/agent-result", response_model=NativeAgentResponse)
def native_agent_result(request: Request, task_id: UUID, user: CurrentUser) -> dict:
    with request.app.state.sessions() as session:
        task = get_task(session, task_id, user.id)
        run = session.get(AgentRun, task_id)
        if run is None or task.runner_type != "agent":
            raise APIError(404, "AGENT_RESULT_NOT_FOUND", "该任务没有原生 Agent 运行记录")
        return {"task_id": task_id, "dispatch_id": run.dispatch_id, "input_sha256": run.input_sha256,
            "status": task.status, "remote_job_id": run.remote_job_id, "result": run.result}


@router.delete("/api/v1/tasks/{task_id}", status_code=204)
def delete_task(request: Request, task_id: UUID, user: CurrentUser) -> None:
    with request.app.state.sessions.begin() as session:
        task = session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user.id).with_for_update())
        if task is None:
            raise APIError(404, "TASK_NOT_FOUND", "研究记录不存在")
        if task.status == "running" or (
            task.runner_type == "agent" and task.status == "queued" and task.started_at is not None
        ):
            raise APIError(409, "TASK_RUNNING", "研究正在执行，请等待完成后再删除")
        if (task.runner_type == "agent" and task.status == "failed"
            and task.run_config.get("transport") in {"local-process-v1", "tacc-ssh-slurm-v1"}
            and not task.run_config.get("agent_cancel_confirmed")):
            run = session.get(AgentRun, task_id)
            if run is not None and run.result is None:
                raise APIError(409, "AGENT_STOP_PENDING", "Agent 作业尚未确认停止，请稍后再删除")
        # Existing cascades remove artifacts, citations, events and task-paper references.
        # Original papers remain and may still be referenced by other tasks.
        session.delete(task)


@router.get("/api/v1/tasks/{task_id}/events", response_model=EventPage)
def task_events(
    request: Request, task_id: UUID, user: CurrentUser, after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    with request.app.state.sessions() as session:
        get_task(session, task_id, user.id)
        events = list(session.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.seq > after_seq)
            .order_by(TaskEvent.seq).limit(limit + 1)
        ))
        items = [
            {name: getattr(event, name) for name in (
                "task_id", "seq", "event_type", "status", "stage", "message", "payload", "created_at"
            )} for event in events[:limit]
        ]
        return {
            "items": items, "next_after_seq": items[-1]["seq"] if items else after_seq,
            "has_more": len(events) > limit,
        }


@router.get("/api/v1/tasks/{task_id}/artifacts", response_model=ArtifactList)
def task_artifacts(request: Request, task_id: UUID, user: CurrentUser) -> dict:
    with request.app.state.sessions() as session:
        task = get_task(session, task_id, user.id)
        if task.status != "succeeded":
            return {"items": []}
        artifact = session.scalar(select(Artifact).where(Artifact.task_id == task_id))
        if artifact is None or task.runner_type not in {"mock", "langgraph", "agent"}:
            raise APIError(500, "INTERNAL_ERROR", "任务结果不可用")
        citation_rows = list(session.execute(
            select(Citation, Paper.title).join(Paper, Paper.id == Citation.paper_id)
            .where(Citation.artifact_id == artifact.id)
        ))
        citation_rows.sort(key=lambda row: int(row[0].citation_key[1:]))
        run = session.get(AgentRun, task_id) if task.runner_type == "agent" else None
        agent_result = (run.result or {}) if run is not None else {}
        comparison = agent_result.get("comparison_table")
        if comparison:
            comparison = normalize_citation_references(comparison,
                {citation.agent_chunk_id: citation.citation_key for citation, _title in citation_rows
                    if citation.agent_chunk_id is not None})
        return {"items": [{
            **{name: getattr(artifact, name) for name in (
                "id", "task_id", "schema_version", "title", "content_markdown", "comparison_table", "created_at"
            )},
            "task_type": task.task_type, "is_mock": task.runner_type == "mock",
            "comparison_markdown": comparison,
            "agent_stop_reason": agent_result.get("stop_reason"),
            "unresolved": agent_result.get("unresolved", []),
            "citations": [{
                "id": citation.id, "citation_key": citation.citation_key,
                "paper_id": citation.paper_id, "paper_title": paper_title,
                "chunk_id": citation.chunk_id if citation.chunk_id is not None else citation.agent_chunk_id,
                "agent_source_id": citation.agent_source_id, "page_number": citation.page_number,
                "quote": citation.quote,
            } for citation, paper_title in citation_rows],
        }]}
