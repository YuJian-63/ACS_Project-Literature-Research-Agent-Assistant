import logging
from datetime import datetime, timedelta
from threading import Event, Thread
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Task, TaskEvent

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


def claim_task(sessions: sessionmaker[Session], owner: UUID, runner_type: str = "agent") -> UUID | None:
    if runner_type != "agent":
        raise ValueError("Only the independent Agent runner is supported")
    with sessions.begin() as session:
        task = session.scalar(
            select(Task).where(Task.status == "queued", Task.runner_type == "agent")
            .order_by(Task.created_at, Task.id).limit(1).with_for_update(skip_locked=True)
        )
        if task is None:
            return None
        now = database_time(session)
        if task.started_at is not None and task.started_at + timedelta(seconds=task.timeout_seconds) <= now:
            mark_failed(session, task, now, "TASK_TIMEOUT", "任务超过执行时间预算")
            return None
        task.status = "running"
        task.stage = "agent_packaging"
        task.worker_id = owner
        if task.started_at is None:
            task.started_at = now
        task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        append_event(session, task, now, "正在准备 Agent 输入文件", "status")
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


def reap_expired(sessions: sessionmaker[Session]) -> int:
    with sessions.begin() as session:
        tasks = list(session.scalars(
            select(Task).where(
                or_(
                    and_(Task.runner_type != "agent", Task.status.in_(["running", "queued"])),
                    and_(Task.status == "running", Task.lease_expires_at <= func.clock_timestamp()),
                    and_(Task.status.in_(["running", "queued"]), Task.started_at + Task.timeout_seconds * text("interval '1 second'") <= func.clock_timestamp()),
                ),
            ).order_by(Task.id).limit(100).with_for_update(skip_locked=True)
        ))
        now = database_time(session)
        for task in tasks:
            if task.runner_type != "agent":
                mark_failed(session, task, now, "RUNNER_RETIRED", "后端内置执行器已停用，请重新提交给独立 Agent")
            elif task.started_at + timedelta(seconds=task.timeout_seconds) <= now:
                mark_failed(session, task, now, "TASK_TIMEOUT", "任务超过执行时间预算")
            else:
                task.status = "queued"
                task.stage = "queued"
                task.worker_id = None
                task.lease_expires_at = None
                append_event(session, task, now, "派发 Worker 已中断，将继续等待同一 Agent 派发结果", "warning")
        return len(tasks)


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
