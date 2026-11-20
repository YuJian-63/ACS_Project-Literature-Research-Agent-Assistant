import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Event
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Paper
from app.db.session import create_database_engine, create_session_factory
from app.db.leases import HEARTBEAT_SECONDS, MONITOR_SECONDS
from app.papers.lifecycle import claim_parse, fail_parse, finish_parse, reap_parses, renew_parse
from app.papers.pdf_parser import MAX_TEXT_BYTES, ParseFailure, ParseResult

logger = logging.getLogger(__name__)


class ParserWorker:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings) -> None:
        self.sessions = sessions
        self.settings = settings
        self.owner = uuid4()
        self.stopped = Event()

    def recover(self) -> None:
        while reap_parses(self.sessions) == 100 and not self.stopped.is_set():
            pass

    def extract(self, paper_id, source_hash: str, size_bytes: int) -> ParseResult:
        root = self.settings.storage_root
        workspace = root / "parse-temp"
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workspace) as temporary:
            result_path = Path(temporary) / "result.json"
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "papers" / "pdf_parser.py"), str(root / "uploads" / f"{paper_id}.pdf"),
                       str(result_path), source_hash, str(size_bytes)]
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
            environment["PYTHONIOENCODING"] = "utf-8"
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     env=environment, cwd=Path(__file__).resolve().parents[2], **options)
            started = last_heartbeat = last_recovery = time.monotonic()
            try:
                while child.poll() is None:
                    now = time.monotonic()
                    if self.stopped.is_set():
                        raise ParseFailure("PARSER_STOPPED", "解析 Worker 已停止，请重新上传以重试")
                    if now - started >= self.settings.parser_timeout_seconds:
                        raise ParseFailure("PDF_PARSE_TIMEOUT", "PDF 解析超过时间限制，请重新上传其他版本")
                    if now - last_heartbeat >= HEARTBEAT_SECONDS:
                        if not renew_parse(self.sessions, paper_id, self.owner):
                            raise ParseFailure("PARSER_LOST", "解析所有权已失效")
                        last_heartbeat = now
                    if now - last_recovery >= MONITOR_SECONDS:
                        self.recover()
                        last_recovery = now
                    self.stopped.wait(.1)
                if self.stopped.is_set():
                    raise ParseFailure("PARSER_STOPPED", "解析 Worker 已停止，请重新上传以重试")
                if time.monotonic() - started >= self.settings.parser_timeout_seconds:
                    raise ParseFailure("PDF_PARSE_TIMEOUT", "PDF 解析超过时间限制，请重新上传其他版本")
                if child.returncode != 0 or not result_path.exists() or result_path.stat().st_size > MAX_TEXT_BYTES * 8:
                    raise ParseFailure("PDF_PARSE_FAILED", "PDF 解析进程异常退出或结果超限")
                output = json.loads(result_path.read_text(encoding="utf-8"))
                if "error" in output:
                    raise ParseFailure(output["error"]["code"], output["error"]["message"])
                return ParseResult.model_validate(output)
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait()

    def run_once(self) -> bool:
        if self.stopped.is_set():
            return False
        paper_id = claim_parse(self.sessions, self.owner)
        if paper_id is None:
            return False
        try:
            with self.sessions() as session:
                paper = session.get(Paper, paper_id)
                source_hash, size_bytes = paper.sha256, paper.size_bytes
            result = self.extract(paper_id, source_hash, size_bytes)
            finish_parse(self.sessions, paper_id, self.owner, source_hash, result)
        except Exception as failure:
            code = failure.code if isinstance(failure, ParseFailure) else "PDF_PARSE_FAILED"
            message = failure.message if isinstance(failure, ParseFailure) else "PDF 解析失败，请重新上传以重试"
            logger.warning("PDF parsing ended: paper_id=%s code=%s", paper_id, code)
            try:
                fail_parse(self.sessions, paper_id, self.owner, code, message)
            except Exception:
                logger.warning("Parser failure recording deferred: paper_id=%s", paper_id)
        return True

    def run(self) -> None:
        while not self.stopped.is_set():
            try:
                self.recover()
                if self.run_once():
                    continue
            except Exception:
                logger.warning("Parser claim/recovery deferred; database may not be ready")
            self.stopped.wait(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings()
    engine = create_database_engine(settings)
    worker = ParserWorker(create_session_factory(engine), settings)
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, lambda *_: worker.stopped.set())
    try:
        worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
