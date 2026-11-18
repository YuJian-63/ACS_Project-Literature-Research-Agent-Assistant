import logging
import signal
import time
from contextlib import contextmanager
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import func, select

from app.sources.arxiv import ArxivClient, ArxivError, ArxivPaper
from app.sources.arxiv_transport import SupervisedArxivTransport
from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.sources.imports import (
    HEARTBEAT_SECONDS, ImportCommitPending, claim_import, complete_import,
    fail_import, heartbeat_import, recover_imports, staging_path,
)
from app.sources.access import source_permit

logger = logging.getLogger(__name__)


class ImportWorker:
    def __init__(self, sessions, settings: Settings, *, client_factory=None):
        self.sessions = sessions
        self.settings = settings
        self.owner = uuid4()
        self.stopped = Event()
        self.client_factory = client_factory

    def run_once(self) -> bool:
        if self.stopped.is_set():
            return False
        recover_imports(self.sessions, root=self.settings.storage_root)
        job = claim_import(self.sessions, self.owner)
        if job is None:
            return False
        lost = Event()
        done = Event()
        with self.sessions() as session:
            now = session.scalar(select(func.clock_timestamp()))
        deadline = time.monotonic() + max(0, (job.deadline - now).total_seconds())
        phase_deadline = deadline

        def heartbeat():
            while not done.wait(HEARTBEAT_SECONDS):
                try:
                    if not heartbeat_import(self.sessions, job):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    return

        thread = Thread(target=heartbeat, daemon=True)
        thread.start()

        def cancelled():
            return self.stopped.is_set() or lost.is_set() or time.monotonic() >= deadline

        def permits():
            while not cancelled() and time.monotonic() < phase_deadline:
                try:
                    context = source_permit(self.sessions)
                    cooldown = context.__enter__()
                    break
                except ArxivError as error:
                    if error.code != "ARXIV_RATE_LIMITED":
                        raise
                    self.stopped.wait(min(1, max(.01, min(deadline, phase_deadline) - time.monotonic())))
            else:
                if time.monotonic() >= phase_deadline:
                    raise ArxivError("ARXIV_TIMEOUT", "arXiv 请求超时", retryable=True)
                raise ArxivError("REQUEST_CANCELLED", "导入请求已中止", retryable=True)
            @contextmanager
            def acquired():
                try:
                    yield cooldown
                finally:
                    context.__exit__(None, None, None)
            return acquired()

        @contextmanager
        def prepared_client(seconds):
            nonlocal phase_deadline
            phase_deadline = deadline
            context = permits()
            initial_cooldown = context.__enter__()
            phase_deadline = min(deadline, time.monotonic() + seconds)
            released = False

            @contextmanager
            def request_permits():
                nonlocal released
                if not released:
                    try:
                        yield initial_cooldown
                    finally:
                        released = True
                        context.__exit__(None, None, None)
                else:
                    with permits() as cooldown:
                        yield cooldown

            try:
                yield ArxivClient(SupervisedArxivTransport(
                    self.settings.arxiv_contact_email, request_permits, cancelled=cancelled,
                ))
            finally:
                if not released:
                    context.__exit__(None, None, None)
                phase_deadline = deadline

        staged = None
        stage = 'metadata'
        attempt_started = time.monotonic()
        try:
            staged = staging_path(self.settings.storage_root, job)
            staged.parent.mkdir(parents=True, exist_ok=True)
            metadata = None
            if job.source_metadata is not None:
                try:
                    metadata = ArxivPaper.model_validate(job.source_metadata)
                except ValueError:
                    raise ArxivError('ARXIV_INVALID_RESPONSE', '已保存的来源元数据无效', phase='response_validation') from None
                if metadata.external_id != job.external_id:
                    raise ArxivError('ARXIV_VERSION_MISMATCH', '来源元数据版本与请求不一致', phase='response_validation')
            if self.client_factory:
                client = self.client_factory(job, cancelled)
                if metadata is None:
                    metadata = client.fetch_metadata(job.external_id)
                stage = 'pdf'
                receipt = client.download_pdf(job.external_id, staged, deadline=deadline)
            else:
                if metadata is None:
                    with prepared_client(20) as client:
                        metadata = client.fetch_metadata(job.external_id)
                stage = 'pdf'
                with prepared_client(90) as client:
                    receipt = client.download_pdf(job.external_id, staged, deadline=phase_deadline)
            if cancelled():
                raise ArxivError("REQUEST_CANCELLED", "导入请求已中止", retryable=True)
            stage = 'commit'
            complete_import(self.sessions, job, metadata, receipt, root=self.settings.storage_root)
        except ImportCommitPending:
            logger.warning("Import completion deferred: import_id=%s", job.import_id)
        except Exception as error:
            if isinstance(error, ArxivError):
                code, message, retryable = error.code, error.message, error.retryable
            else:
                code, message, retryable = "STORAGE_WRITE_FAILED", "论文导入暂时失败", True
            if code == "REQUEST_CANCELLED":
                code = "IMPORT_WORKER_STOPPED" if self.stopped.is_set() else "IMPORT_LEASE_EXPIRED"
                message = "导入 Worker 已停止" if self.stopped.is_set() else "导入执行已失效"
            logger.warning('Import failed: import_id=%s stage=%s phase=%s elapsed_ms=%d code=%s',
                           job.import_id, stage, error.phase if isinstance(error, ArxivError) else 'unknown',
                           round((time.monotonic() - attempt_started) * 1000), code)
            try:
                fail_import(self.sessions, job, code, message, retryable)
            except Exception:
                logger.warning("Import failure recording deferred: import_id=%s", job.import_id)
        finally:
            done.set()
            thread.join()
            try:
                if staged is not None:
                    staged.unlink(missing_ok=True)
            except OSError:
                logger.warning("Import staging cleanup deferred: import_id=%s", job.import_id)
        return True

    def run(self) -> None:
        while not self.stopped.is_set():
            try:
                if self.run_once():
                    continue
            except Exception:
                logger.warning("Import claim/recovery deferred; database may not be ready")
            self.stopped.wait(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings()
    if not settings.arxiv_configured:
        raise SystemExit("ARXIV_ENABLED=true and ARXIV_CONTACT_EMAIL are required")
    engine = create_database_engine(settings)
    worker = ImportWorker(create_session_factory(engine), settings)
    for number in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(number, lambda *_: worker.stopped.set())
    try:
        worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
