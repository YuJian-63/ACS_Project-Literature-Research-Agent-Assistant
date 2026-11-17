import logging
from datetime import datetime, timedelta
from threading import Event, Thread
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Artifact, Citation, Task, TaskEvent
from app.research.validation import ValidatedResult

logger = logging.getLogger(__name__)
LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 20
MONITOR_SECONDS = 10


def database_time(session: Session) -> datetime:
    return session.scalar(select(func.clock_timestamp()))


def append_event(session: Session, task: Task, now: datetime, message: str, event_type: str, payload: dict | None = None) -> None:
    task.last_event_seq += 1
    task.updated_at = now
    session.add(TaskEvent(
        task_id=task.id, seq=task.last_event_seq, event_type=event_type,
        status=task.status, stage=task.stage, message=message, payload=payload or {}, created_at=now,
    ))


def owns_task(task: Task | None, owner: UUID, now: datetime) -> bool:
    return (
        task is not None and task.status == "running" and task.worker_id == owner
        and task.lease_expires_at > now
        and task.started_at + timedelta(seconds=task.timeout_seconds) > now
    )


def claim_task(sessions: sessionmaker[Session], owner: UUID, runner_type: str = "mock") -> UUID | None:
    if runner_type not in {"mock", "langgraph", "agent"}:
        raise ValueError("Unsupported runner type")
    with sessions.begin() as session:
        task = session.scalar(
            select(Task).where(Task.status == "queued", Task.runner_type == runner_type)
            .order_by(Task.created_at, Task.id).limit(1).with_for_update(skip_locked=True)
        )
        if task is None:
            return None
        now = database_time(session)
        staged_review = task.workflow_version in {"langgraph-review-v2", "langgraph-search-v1"}
        if staged_review and task.started_at is not None and task.started_at + timedelta(seconds=task.timeout_seconds) <= now:
            mark_failed(session, task, now, "TASK_TIMEOUT", "任务超过执行时间预算")
            return None
        task.status = "running"
        task.stage = "mock_preparing" if runner_type == "mock" else "retrieving"
        task.worker_id = owner
        if not staged_review or task.started_at is None:
            task.started_at = now
        task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        message = ("模拟任务开始执行，尚未分析论文" if runner_type == "mock" else
                   "Agent 研究任务开始执行" if runner_type == "agent" else
                   "真实研究任务开始，正在读取已解析证据")
        append_event(session, task, now, message, "status")
        return task.id


def set_task_stage(
    sessions: sessionmaker[Session], task_id: UUID, owner: UUID, expected: str, stage: str, message: str
) -> bool:
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now) or task.stage != expected:
            return False
        task.stage = stage
        append_event(session, task, now, message, "stage")
        return True


def locked_task(session: Session, task_id: UUID) -> Task | None:
    return session.scalar(select(Task).where(Task.id == task_id).with_for_update())


def heartbeat(sessions: sessionmaker[Session], task_id: UUID, owner: UUID) -> bool:
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now):
            return False
        task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        task.updated_at = now
        return True


def advance_task(sessions: sessionmaker[Session], task_id: UUID, owner: UUID) -> bool:
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now):
            return False
        if task.stage != "mock_preparing":
            return False
        task.stage = "mock_generating"
        append_event(session, task, now, "正在生成流程演示用模拟结果", "stage")
        return True


def mark_failed(session: Session, task: Task, now: datetime, code: str, message: str) -> None:
    task.status = "failed"
    task.stage = "failed"
    task.finished_at = now
    task.worker_id = None
    task.lease_expires_at = None
    task.error_code = code
    task.error_message = message
    task.error_details = {}
    append_event(session, task, now, message, "error")


def fail_owned(
    sessions: sessionmaker[Session], task_id: UUID, owner: UUID, code: str, message: str,
    *, details: dict | None = None,
) -> bool:
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now):
            return False
        mark_failed(session, task, now, code, message)
        if details is not None:
            task.error_details = dict(details)
        return True


def complete_mock(sessions: sessionmaker[Session], task_id: UUID, owner: UUID) -> bool:
    content = (
        "## 模拟结果\n\n此内容仅用于验证上传、排队、执行与轮询流程。"
        "尚未解析或分析论文，未调用模型，不代表论文结论。\n\n"
        "不提供模拟证据、引用或研究指标；请勿将此结果用于模型效果评估。"
    )
    if not content.strip() or len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Invalid mock result")
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now) or task.stage != "mock_generating":
            return False
        if task.runner_type != "mock":
            raise ValueError("Mock result requires mock task")
        titles = {"summary": "论文摘要", "qa": "论文问答", "review": "论文综述"}
        session.add(Artifact(
            task_id=task.id, title=f"{titles[task.task_type]}（模拟结果）",
            content_markdown=content, comparison_table=None, created_at=now,
        ))
        task.status = "succeeded"
        task.stage = "mock_completed"
        task.finished_at = now
        task.worker_id = None
        task.lease_expires_at = None
        append_event(session, task, now, "模拟流程完成，结果不代表论文结论", "status")
        return True


def complete_real(
    sessions: sessionmaker[Session], task_id: UUID, owner: UUID, result: ValidatedResult,
    *, input_tokens: int | None, output_tokens: int | None, model_calls: int,
) -> bool:
    for value in (input_tokens, output_tokens, model_calls):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Invalid model usage")
    if type(model_calls) is not int:
        raise ValueError("Model call count is required")
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now) or task.runner_type != "langgraph":
            return False
        if task.stage not in {"generating", "writing", "validating"}:
            return False
        if input_tokens is not None and output_tokens is not None and input_tokens + output_tokens > task.max_tokens:
            mark_failed(session, task, now, "BUDGET_EXCEEDED", "模型用量超过任务 Token 预算")
            return False
        if (task.task_type == "review") != (result.comparison_table is not None):
            raise ValueError("Comparison table does not match the task type")
        title = {"summary": "论文摘要", "qa": "论文问答", "review": "论文综述"}[task.task_type]
        artifact = Artifact(
            task_id=task.id, title=title, content_markdown=result.content_markdown,
            comparison_table=result.comparison_table, created_at=now,
        )
        session.add(artifact)
        session.flush()
        session.add_all([
            Citation(
                artifact_id=artifact.id, task_id=task.id, citation_key=citation.citation_key,
                paper_id=citation.paper_id, chunk_id=citation.chunk_id,
                page_number=citation.page_number, quote=citation.quote, created_at=now,
            ) for citation in result.citations
        ])
        task.input_tokens = input_tokens
        task.output_tokens = output_tokens
        task.model_calls = model_calls
        task.tool_calls = 0
        task.status = "succeeded"
        task.stage = "completed"
        task.finished_at = now
        task.worker_id = None
        task.lease_expires_at = None
        task.error_code = None
        task.error_message = None
        task.error_details = None
        append_event(session, task, now, "研究结果生成完成，引用来源已校验", "status")
        return True


def reap_expired(sessions: sessionmaker[Session]) -> int:
    with sessions.begin() as session:
        tasks = list(session.scalars(
            select(Task).where(
                or_(
                    and_(Task.status == "running", Task.lease_expires_at <= func.clock_timestamp()),
                    and_(Task.status.in_(["running", "queued"]), Task.started_at + Task.timeout_seconds * text("interval '1 second'") <= func.clock_timestamp()),
                ),
            ).order_by(Task.id).limit(100).with_for_update(skip_locked=True)
        ))
        now = database_time(session)
        count = 0
        for task in tasks:
            if task.started_at + timedelta(seconds=task.timeout_seconds) <= now:
                mark_failed(session, task, now, "TASK_TIMEOUT", "任务超过执行时间预算")
                count += 1
            elif task.lease_expires_at <= now:
                if task.workflow_version in {"langgraph-review-v2", "langgraph-search-v1"}:
                    task.status = "queued"
                    task.stage = "queued"
                    task.worker_id = None
                    task.lease_expires_at = None
                    append_event(session, task, now, "研究执行中断，将从已保存的阶段恢复", "warning")
                else:
                    mark_failed(session, task, now, "WORKER_LOST", "Worker 租约已过期")
                count += 1
        return count


class TaskMonitor:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.stopped = Event()
        self.thread = Thread(target=self.run, name="task-monitor", daemon=True)

    def sweep(self) -> None:
        try:
            while reap_expired(self.sessions) == 100 and not self.stopped.is_set():
                pass
        except Exception:
            logger.warning("Task recovery deferred; database may not be ready")

    def start(self) -> None:
        self.sweep()
        self.thread.start()

    def run(self) -> None:
        while not self.stopped.wait(MONITOR_SECONDS):
            self.sweep()

    def close(self) -> None:
        self.stopped.set()
        self.thread.join()
