import logging
import signal
import threading
from uuid import UUID, uuid4
from zipfile import BadZipFile

from sqlalchemy.orm import Session, sessionmaker

from app.agent_bridge.bundles import canonical_json, export_bundle, read_result
from app.agent_bridge.files import atomic_write
from app.agent_bridge.maintenance import AgentMaintenance, cancel_terminal
from app.agent_bridge.store import complete_delivery, load_execution, record_job
from app.agent_bridge.transport import (
    Transport,
    TransportError,
    create_transport,
    transport_name,
)
from app.auth.agent_library import issue_job_library_token
from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.tasks.lifecycle import (
    HEARTBEAT_SECONDS,
    TaskMonitor,
    claim_task,
    fail_owned,
    heartbeat,
    set_task_stage,
)

logger = logging.getLogger(__name__)


class AgentWorker:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings, *, transport: Transport | None = None):
        self.sessions = sessions
        self.settings = settings
        self.transport = transport if transport is not None else create_transport(settings)
        self.owner = uuid4()
        self.stopped = threading.Event()

    def run_once(self) -> bool:
        task_id = claim_task(self.sessions, self.owner, "agent")
        if task_id is None:
            return False
        self.execute(task_id)
        return True

    def execute(self, task_id: UUID) -> None:
        finished = threading.Event()
        ownership_lost = threading.Event()

        def keep_alive():
            while not finished.wait(HEARTBEAT_SECONDS):
                try:
                    if heartbeat(self.sessions, task_id, self.owner):
                        continue
                except Exception:
                    logger.warning("Agent heartbeat failed: task_id=%s", task_id)
                ownership_lost.set()
                break

        thread = threading.Thread(target=keep_alive, name="agent-heartbeat", daemon=True)
        thread.start()
        try:
            execution = load_execution(self.sessions, task_id, self.owner)
            if execution is None:
                return
            manifest = execution.manifest
            if execution.transport != transport_name(self.settings):
                raise TransportError("AGENT_TRANSPORT_CHANGED")
            bundle = export_bundle(manifest, self.settings.storage_root, self.settings.resolved_agent_exchange_root,
                include_pdfs=self.settings.agent_transport != "tcloud")
            if self.settings.agent_library_public_url:
                token = issue_job_library_token(self.settings, manifest.dispatch_id, execution.deadline)
                atomic_write(bundle.with_name("library-access.json"), canonical_json({
                    "base_url": self.settings.agent_library_public_url, "token": token,
                }))
            if ownership_lost.is_set() or not set_task_stage(self.sessions, task_id, self.owner,
                "agent_packaging", "agent_waiting", "输入文件已就绪，正在派发并等待 Agent 结果"):
                return
            uploaded, submitted = False, False
            job_id = execution.job_id
            retries = 0
            while not self.stopped.is_set() and not ownership_lost.is_set():
                try:
                    if not uploaded:
                        self.transport.upload(manifest, bundle)
                        uploaded = True
                    if not submitted:
                        if ownership_lost.is_set() or not heartbeat(self.sessions, task_id, self.owner):
                            return
                        job_id = self.transport.submit(manifest, job_id, deadline=execution.deadline)
                        if job_id is not None and not record_job(self.sessions, task_id, self.owner, manifest, job_id):
                            return
                        submitted = True
                    status = self.transport.poll(manifest, job_id)
                    incoming = self.transport.download(manifest, job_id)
                    if incoming is not None:
                        envelope = read_result(incoming, self.settings.agent_result_max_bytes)
                        if status is not None and status.remote_job_id != envelope.remote_job_id:
                            raise ValueError("Agent status and result job identities disagree")
                        if status is not None and status.state != "running" and (status.error is not None or status.stop_reason != envelope.result.stop_reason):
                            raise ValueError("Agent status and result disagree")
                        complete_delivery(self.sessions, task_id, self.owner, manifest, envelope, settings=self.settings)
                        return
                    if status is not None and status.state != "running":
                        code = "AGENT_WRAPPER_FAILED" if status.error else "AGENT_RESULT_MISSING"
                        details = {"wrapper_code": status.error.code, "wrapper_type": status.error.type} if status.error else {}
                        fail_owned(self.sessions, task_id, self.owner, code, "Agent 执行失败或未返回完整研究结果", details=details)
                        return
                    retries = 0
                except TransportError as exc:
                    if not exc.retryable:
                        raise
                    retries += 1
                    logger.warning("Agent transport will retry: task_id=%s code=%s", task_id, exc.code)
                    self.stopped.wait(min(30, self.settings.agent_poll_seconds * 2 ** min(retries, 4)))
                    continue
                self.stopped.wait(self.settings.agent_poll_seconds)
        except TransportError as exc:
            fail_owned(self.sessions, task_id, self.owner, exc.code, "Agent 派发或平台执行失败，请查看执行记录", details={"transport_error": exc.code})
        except (ValueError, OSError, EOFError, BadZipFile, RecursionError):
            fail_owned(self.sessions, task_id, self.owner, "AGENT_DELIVERY_INVALID", "Agent 输入或结果文件不合法，未覆盖已有数据")
        except Exception:
            logger.warning("Agent exchange deferred: task_id=%s", task_id)
        finally:
            finished.set()
            thread.join()
            try:
                cancel_terminal(self.sessions, self.settings, task_id, self.transport)
            except Exception:
                logger.warning("Agent terminal reconciliation deferred: task_id=%s", task_id)

    def run(self) -> None:
        monitor = TaskMonitor(self.sessions)
        maintenance = AgentMaintenance(self.sessions, self.settings)
        monitor.start()
        maintenance.start()
        try:
            while not self.stopped.is_set():
                try:
                    if self.run_once():
                        continue
                except Exception:
                    logger.warning("Agent task claim deferred; database may not be ready")
                self.stopped.wait(1)
        finally:
            monitor.close()
            maintenance.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings()
    if settings.task_runner != "agent" or not settings.agent_dispatch_enabled:
        raise SystemExit("TASK_RUNNER=agent and AGENT_DISPATCH_ENABLED=true are required")
    engine = create_database_engine(settings)
    worker = AgentWorker(create_session_factory(engine), settings)
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, lambda *_: worker.stopped.set())
    try:
        worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
