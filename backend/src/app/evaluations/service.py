import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import AgentRun, Artifact, Citation, EvaluationDailyQuota, Paper, Task, TaskEvaluation, TaskPaper
from app.errors import APIError
from app.evaluations.contracts import EvaluationFailure, PROMPT_VERSION, RUBRIC_VERSION, WEIGHTS
from app.tasks.lifecycle import database_time


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def configuration(settings) -> dict:
    return {"provider": "deepseek", "base_url": settings.evaluation_base_url, "model": settings.evaluation_model,
        "rubric_version": RUBRIC_VERSION, "prompt_version": PROMPT_VERSION, "weights": WEIGHTS,
        "timeout_seconds": settings.evaluation_timeout_seconds,
        "max_output_tokens": settings.evaluation_max_output_tokens,
        "max_input_bytes": settings.evaluation_max_input_bytes,
        "max_response_bytes": settings.evaluation_max_response_bytes,
        "max_attempts": settings.evaluation_max_attempts,
        "evidence_timeout_seconds": settings.evaluation_evidence_timeout_seconds}


def result_input(session, task, run) -> dict:
    result = run.result if run and run.result else {}
    keys = dict(session.execute(select(Citation.agent_chunk_id, Citation.citation_key)
        .where(Citation.task_id == task.id)).all())
    citations = []
    for index, citation in enumerate(result.get("citations", []), 1):
        citations.append({**citation, "key": keys.get(citation["chunk_id"], f"E{index}")})
    papers = session.execute(select(Paper).join(TaskPaper, TaskPaper.paper_id == Paper.id)
        .where(TaskPaper.task_id == task.id, Paper.user_id == task.user_id).order_by(Paper.id)).scalars().all()
    return {"task_type": task.task_type, "question": task.question or "Summarize the selected papers.",
        "answer": result.get("answer", ""), "comparison_table": result.get("comparison_table", ""),
        "citations": citations, "sources": result.get("sources", []),
        "stop_reason": result.get("stop_reason"), "unresolved": result.get("unresolved", []),
        "original_sources": [{"paper_id": str(paper.id), "sha256": paper.sha256,
            "storage_key": paper.storage_key, "page_count": paper.page_count} for paper in papers]}


def reserve_daily_allowance(session, user_id, now, limit) -> bool:
    day = now.astimezone(timezone.utc).date()
    session.execute(insert(EvaluationDailyQuota).values(user_id=user_id, day=day, reserved=0).on_conflict_do_nothing())
    quota = session.scalar(select(EvaluationDailyQuota).where(EvaluationDailyQuota.user_id == user_id,
        EvaluationDailyQuota.day == day).with_for_update())
    if quota.reserved >= limit:
        return False
    quota.reserved += 1
    return True


def enqueue_evaluation(session, task, settings, *, automatic: bool = False):
    run = session.get(AgentRun, task.id)
    if task.runner_type != "agent" or task.status not in {"succeeded", "failed"}:
        raise APIError(409, "EVALUATION_NOT_READY", "The Agent result is not available for evaluation")
    artifact = session.scalar(select(Artifact).where(Artifact.task_id == task.id))
    payload = result_input(session, task, run)
    config = configuration(settings)
    input_hash, config_hash = digest(payload), digest(config)
    existing = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task.id,
        TaskEvaluation.input_sha256 == input_hash, TaskEvaluation.config_sha256 == config_hash).with_for_update())
    now = database_time(session)
    if existing:
        quota_skipped = existing.status == "skipped" and existing.error_code == "DAILY_EVALUATION_LIMIT"
        if not automatic and (existing.status == "failed" or quota_skipped):
            if existing.attempts >= config["max_attempts"]:
                raise APIError(409, "EVALUATION_ATTEMPTS_EXHAUSTED", "Evaluation attempt limit reached")
            if quota_skipped and not reserve_daily_allowance(session, task.user_id, now, settings.evaluation_daily_limit):
                raise APIError(429, "DAILY_EVALUATION_LIMIT", "Daily evaluation allowance reached")
            existing.status, existing.error_code, existing.finished_at = "pending", None, None
            existing.next_attempt_at = existing.updated_at = now
        return existing
    usable = bool(artifact and run and run.stop_reason in {"completed", "partial"})
    error = None if usable else "NO_USABLE_RESULT"
    status = "pending" if usable else "skipped"
    if usable and not reserve_daily_allowance(session, task.user_id, now, settings.evaluation_daily_limit):
        if not automatic:
            raise APIError(429, "DAILY_EVALUATION_LIMIT", "Daily evaluation allowance reached")
        status, error = "skipped", "DAILY_EVALUATION_LIMIT"
    if status == "pending" and len(canonical(payload)) > config["max_input_bytes"]:
        status, error = "failed", "EVALUATION_INPUT_TOO_LARGE"
    row = TaskEvaluation(task_id=task.id, artifact_id=artifact.id if artifact else None,
        input_sha256=input_hash, config_sha256=config_hash, input_payload=payload, config=config,
        status=status, error_code=error, attempts=0, next_attempt_at=now,
        finished_at=now if status in {"failed", "skipped"} else None, created_at=now, updated_at=now)
    session.add(row)
    session.flush()
    return row


@dataclass(frozen=True)
class EvaluationClaim:
    id: UUID
    task_id: UUID
    lease_token: UUID
    attempts: int
    input_payload: dict
    config: dict
    config_sha256: str
    input_sha256: str
    evidence: dict | None
    evidence_sha256: str | None


def claim_evaluation(sessions, settings) -> EvaluationClaim | None:
    with sessions.begin() as session:
        now = database_time(session)
        for _attempt in range(10):
            row = session.scalar(select(TaskEvaluation).where(or_(
                (TaskEvaluation.status == "pending") & (TaskEvaluation.next_attempt_at <= now),
                (TaskEvaluation.status == "running") & (TaskEvaluation.lease_expires_at <= now)))
                .order_by(TaskEvaluation.next_attempt_at, TaskEvaluation.created_at, TaskEvaluation.id)
                .limit(1).with_for_update(skip_locked=True))
            if row is None:
                return None
            if row.attempts >= row.config["max_attempts"]:
                row.status, row.error_code = "failed", "EVALUATION_ATTEMPTS_EXHAUSTED"
                row.finished_at = row.updated_at = now
                row.lease_token = row.lease_expires_at = None
                session.flush()
                continue
            row.status, row.lease_token = "running", uuid4()
            row.attempts += 1
            row.started_at = row.started_at or now
            row.updated_at = now
            row.lease_expires_at = now + timedelta(seconds=row.config["timeout_seconds"]
                + row.config["evidence_timeout_seconds"] + 60)
            return EvaluationClaim(row.id, row.task_id, row.lease_token, row.attempts,
                row.input_payload, row.config, row.config_sha256, row.input_sha256, row.evidence, row.evidence_sha256)
    return None


def save_evidence(sessions, claim, evidence) -> bool:
    with sessions.begin() as session:
        row = session.get(TaskEvaluation, claim.id, with_for_update=True)
        now = database_time(session)
        if not owned(row, claim, now):
            return False
        row.evidence, row.evidence_sha256, row.updated_at = evidence, digest(evidence), now
        return True


def owned(row, claim, now) -> bool:
    return bool(row and row.status == "running" and row.lease_token == claim.lease_token and row.lease_expires_at > now)


def finish_evaluation(sessions, claim, *, report=None, usage=None, error: EvaluationFailure | None = None) -> bool:
    with sessions.begin() as session:
        row = session.get(TaskEvaluation, claim.id, with_for_update=True)
        now = database_time(session)
        if not owned(row, claim, now):
            return False
        if error:
            row.error_code = error.code
            row.status = "pending" if error.retryable and row.attempts < row.config["max_attempts"] else "failed"
            row.next_attempt_at = now + timedelta(seconds=min(300, 15 * 2 ** (row.attempts - 1)))
        else:
            row.status, row.report, row.usage, row.error_code = "succeeded", report, usage, None
        row.finished_at = None if row.status == "pending" else now
        row.lease_token = row.lease_expires_at = None
        row.updated_at = now
        return True
