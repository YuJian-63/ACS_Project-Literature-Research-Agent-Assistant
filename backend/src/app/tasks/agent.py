"""Agent-native task persistence; no local paper/chunk identity requirements."""

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.schemas import AgentTaskCreate
from app.api.views import accepted_view
from app.db.models import Task, TaskEvent
from app.db.ownership import check_task_capacity, lock_active_user
from app.errors import APIError
from app.tasks.lifecycle import (
    append_event,
    database_time,
    locked_task,
    mark_failed,
    owns_task,
)
from app.tasks.service import validate_idempotency_key


def agent_available(python: str) -> bool:
    return Path(python).is_file() and os.access(python, os.X_OK)


def submit_agent_task(
    sessions,
    settings,
    request: AgentTaskCreate,
    key: str | None,
    *,
    user_id: UUID,
    request_digest: str | None = None,
):
    validate_idempotency_key(key)
    digest = hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    if request_digest is not None:
        digest = request_digest

    def replay(task):
        if task.request_hash != digest:
            raise APIError(409, "IDEMPOTENCY_CONFLICT", "该幂等键已用于不同请求")
        return accepted_view(task), True

    try:
        with sessions.begin() as session:
            lock_active_user(session, user_id)
            if key:
                previous = session.scalar(
                    select(Task).where(
                        Task.user_id == user_id, Task.idempotency_key == key
                    )
                )
                if previous is not None:
                    return replay(previous)
            check_task_capacity(
                session, user_id, settings.user_active_tasks, settings.user_daily_tasks
            )
            if not agent_available(settings.agent_python):
                raise APIError(
                    503, "RUNNER_NOT_CONFIGURED", "Agent Python 环境尚未配置"
                )
            identity = uuid4()
            now = datetime.now(timezone.utc)
            payload = request.model_dump(exclude={"task_type"}, mode="json")
            payload["task_id"] = str(identity)
            task = Task(
                id=identity,
                user_id=user_id,
                task_type=request.task_type,
                question=request.question,
                workflow_type="baseline",
                runner_type="agent",
                workflow_version="agent-v1",
                run_config={"budget_mode": "automatic", "legacy_input": True}
                if request_digest
                else {},
                review_state={},
                agent_input=payload,
                agent_result=None,
                max_steps=request.max_steps,
                max_tokens=None,
                timeout_seconds=request.timeout_seconds,
                status="queued",
                stage="queued",
                idempotency_key=key,
                request_hash=digest,
                last_event_seq=1,
                created_at=now,
                updated_at=now,
            )
            session.add(task)
            session.flush()
            session.add(
                TaskEvent(
                    task_id=identity,
                    seq=1,
                    event_type="status",
                    status="queued",
                    stage="queued",
                    message="Agent 任务已加入队列",
                    payload={},
                    created_at=now,
                )
            )
            accepted = accepted_view(task)
        return accepted, False
    except IntegrityError:
        if key:
            with sessions() as session:
                previous = session.scalar(
                    select(Task).where(
                        Task.user_id == user_id, Task.idempotency_key == key
                    )
                )
                if previous is not None:
                    return replay(previous)
        raise


def validated_result(result: dict, task_id: UUID) -> dict:
    from app.tasks.agent_schema import AgentResult

    if len(json.dumps(result, ensure_ascii=False).encode()) > 16 * 1024 * 1024:
        raise ValueError("Agent result is too large")
    result = AgentResult.model_validate(result).model_dump(mode="json")
    if result["task_id"] != str(task_id):
        raise ValueError("Agent returned another task identity")
    return result


def complete_agent(sessions, task_id: UUID, owner: UUID, result: dict) -> bool:
    result = validated_result(result, task_id)
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now) or task.runner_type != "agent":
            return False
        if result["question"] != task.question:
            raise ValueError("Agent question does not match task")
        task.agent_result = result
        model_id = result.get("configuration", {}).get("model")
        if isinstance(model_id, str) and model_id.strip():
            task.model_id = model_id
        usage = result["usage"]
        for field in ("input_tokens", "output_tokens", "model_calls", "tool_calls"):
            setattr(task, field, usage[field])
        if result["stop_reason"] not in {"completed", "partial"}:
            mark_failed(
                session,
                task,
                now,
                "AGENT_" + result["stop_reason"].upper(),
                "Agent 未完成研究，请查看停止原因和未解决项",
            )
        else:
            task.status = "succeeded"
            task.stage = "completed"
            task.finished_at = now
            task.worker_id = None
            task.lease_expires_at = None
            append_event(
                session,
                task,
                now,
                "Agent 部分完成"
                if result["stop_reason"] == "partial"
                else "Agent 研究完成",
                "status",
            )
        return True


def public_agent_result(task, *, trace=False):
    if task.runner_type != "agent":
        raise APIError(409, "RESULT_FORMAT_MISMATCH", "此任务不使用 Agent v1 结果")
    if task.agent_result is None:
        return {"trace": [], "configuration": {}} if trace else None
    result = deepcopy(task.agent_result)
    if trace:
        return redact(
            {
                "trace": result.get("trace", []),
                "configuration": result.get("configuration", {}),
            }
        )
    result.pop("trace", None)
    result.pop("configuration", None)
    return result


def redact(value):
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if any(
                    part in key.lower()
                    for part in (
                        "api_key",
                        "password",
                        "secret",
                        "authorization",
                        "access_token",
                        "refresh_token",
                    )
                )
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
