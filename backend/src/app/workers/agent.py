"""Dedicated worker for isolated Agent v1 function calls."""

import logging
import signal
import threading
from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.db.models import Task
from app.db.session import create_database_engine, create_session_factory
from app.tasks.agent import complete_agent
from app.tasks.lifecycle import (
    HEARTBEAT_SECONDS,
    TaskMonitor,
    claim_task,
    fail_owned,
    heartbeat,
)

logger = logging.getLogger(__name__)


class AgentWorker:
    def __init__(self, sessions, settings, runner=None):
        from app.agent_bridge.subprocess_client import run_agent

        self.sessions = sessions
        self.settings = settings
        self.runner = runner or run_agent
        self.owner = uuid4()
        self.stopped = threading.Event()

    def run_once(self):
        identity = claim_task(self.sessions, self.owner, "agent")
        if identity is None:
            return False
        self.execute(identity)
        return True

    def execute(self, identity):
        from app.agent_bridge.subprocess_client import AgentProcessError

        done = threading.Event()
        lost = threading.Event()

        def renew():
            while not done.wait(HEARTBEAT_SECONDS):
                try:
                    if heartbeat(self.sessions, identity, self.owner):
                        continue
                except Exception:
                    logger.warning("Agent heartbeat failed: task_id=%s", identity)
                lost.set()
                return

        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        try:
            with self.sessions() as session:
                task = session.get(Task, identity)
                payload = dict(task.agent_input)
                remaining = (
                    task.timeout_seconds
                    - (datetime.now(timezone.utc) - task.started_at).total_seconds()
                )
            if remaining <= 0:
                fail_owned(
                    self.sessions,
                    identity,
                    self.owner,
                    "TASK_TIMEOUT",
                    "Agent 任务超时",
                )
                return
            result = self.runner(
                payload,
                python=self.settings.agent_python,
                timeout_seconds=remaining,
                stopped=lambda: self.stopped.is_set() or lost.is_set(),
            )
            if self.stopped.is_set() or lost.is_set():
                return
            complete_agent(self.sessions, identity, self.owner, result)
        except AgentProcessError as error:
            fail_owned(
                self.sessions, identity, self.owner, error.code.upper(), str(error)
            )
        except Exception:
            logger.warning("Agent execution failed: task_id=%s", identity)
            fail_owned(
                self.sessions,
                identity,
                self.owner,
                "AGENT_EXECUTION_FAILED",
                "Agent 执行或结果校验失败",
            )
        finally:
            done.set()
            thread.join(timeout=5)

    def run(self):
        monitor = TaskMonitor(self.sessions)
        monitor.start()
        try:
            while not self.stopped.is_set():
                try:
                    if self.run_once():
                        continue
                except Exception:
                    logger.warning("Agent task claim deferred")
                self.stopped.wait(1)
        finally:
            monitor.close()


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    engine = create_database_engine(settings)
    worker = AgentWorker(create_session_factory(engine), settings)
    for value in (signal.SIGINT, signal.SIGTERM):
        signal.signal(value, lambda *_: worker.stopped.set())
    try:
        worker.run()
    finally:
        engine.dispose()
