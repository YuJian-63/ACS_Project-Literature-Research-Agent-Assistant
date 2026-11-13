import logging
import signal
from threading import Event, Thread
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Task
from app.db.session import create_database_engine, create_session_factory
from app.tasks.lifecycle import (
    HEARTBEAT_SECONDS,
    TaskMonitor,
    advance_task,
    claim_task,
    complete_mock,
    fail_owned,
    heartbeat,
)

logger = logging.getLogger(__name__)


class MockWorker:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.owner = uuid4()
        self.stopped = Event()

    def run_once(self) -> bool:
        task_id = claim_task(self.sessions, self.owner)
        if task_id is None:
            return False
        self.execute(task_id)
        return True

    def execute(self, task_id: UUID) -> None:
        heartbeat_done = Event()
        ownership_lost = Event()

        def renew() -> None:
            while not heartbeat_done.wait(HEARTBEAT_SECONDS):
                try:
                    if heartbeat(self.sessions, task_id, self.owner):
                        continue
                except Exception:
                    logger.warning("Worker heartbeat failed: task_id=%s", task_id)
                ownership_lost.set()
                return

        thread = Thread(target=renew, name="mock-heartbeat", daemon=True)
        thread.start()
        try:
            with self.sessions() as session:
                task = session.get(Task, task_id)
                delay = float(task.run_config["mock_step_delay_seconds"])
                steps = task.max_steps
                if task.workflow_version != "mock-v1" or not 0 <= delay <= 10:
                    raise ValueError("Unsupported frozen execution configuration")
            if self.stopped.wait(delay):
                raise RuntimeError("Worker stopped")
            if ownership_lost.is_set():
                return
            if steps < 2:
                fail_owned(self.sessions, task_id, self.owner, "BUDGET_EXCEEDED", "模拟流程需要至少两步预算")
                return
            if not advance_task(self.sessions, task_id, self.owner):
                return
            if self.stopped.wait(delay):
                raise RuntimeError("Worker stopped")
            if not ownership_lost.is_set():
                complete_mock(self.sessions, task_id, self.owner)
        except Exception:
            logger.warning("Mock execution failed: task_id=%s", task_id)
            try:
                fail_owned(self.sessions, task_id, self.owner, "AGENT_EXECUTION_FAILED", "模拟任务执行失败")
            except Exception:
                logger.warning("Failure recording deferred: task_id=%s", task_id)
        finally:
            heartbeat_done.set()
            thread.join()

    def run(self) -> None:
        monitor = TaskMonitor(self.sessions)
        monitor.start()
        try:
            while not self.stopped.is_set():
                try:
                    if self.run_once():
                        continue
                except Exception:
                    logger.warning("Task claim deferred; database may not be ready")
                self.stopped.wait(1)
        finally:
            monitor.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    engine = create_database_engine(Settings())
    worker = MockWorker(create_session_factory(engine))
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, lambda *_: worker.stopped.set())
    try:
        worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
