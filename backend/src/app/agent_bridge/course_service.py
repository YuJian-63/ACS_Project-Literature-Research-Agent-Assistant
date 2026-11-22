"""Reconcile the database's single managed GPU job from the local TCloud worker."""
import logging
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.agent_bridge.files import atomic_write, dispatch_lock
from app.agent_bridge.tcloud import JOB_ID, ROOT, pre_submit_failure
from app.agent_bridge.transport import TransportError
from app.db.models import CourseService

logger = logging.getLogger(__name__)
READY = ("RUNTIME_MODE=public", "AGENT_TELEMETRY_READY=qwen-agent-telemetry-v1", "Application startup complete.")


def reconcile(sessions, transport, directory):
    # Serialize remote calls across local worker processes without blocking API transactions.
    with dispatch_lock(directory):
        with sessions.begin() as session:
            row = session.get(CourseService, 1, with_for_update=True)
            if not row or row.state in {"stopped", "failed"}:
                return
            state, generation, job, stopping = row.state, row.generation, row.job_id, row.stop_requested
            now = datetime.now(UTC)
            if row.checked_at and not stopping and (now - row.checked_at).total_seconds() < (60 if state == "ready" else 30):
                return
            if state == "requested" and stopping:
                row.state, row.stop_requested = "stopped", False
                return
            if state == "requested":
                row.state = "submitting"
            row.checked_at = now

        receipt = directory / (str(generation) + ".submit")
        detail = url = None
        try:
            if not job:
                if state == "requested":
                    with tempfile.TemporaryDirectory() as tmp:
                        stage = Path(tmp) / ("model-" + str(generation))
                        shutil.copytree(ROOT / "model-server/server", stage, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "configurations", "run.sh"))
                        # If the SDK loses the acknowledgement, recover the identity when Slurm starts the job.
                        (stage / "service-generation").write_text(str(generation))
                        _, output = transport.cli("submit", cwd=stage, timeout=transport.settings.agent_tcloud_submit_timeout_seconds)
                        atomic_write(receipt, output.replace("\0", "").encode())
                output = receipt.read_text() if receipt.exists() else ""
                ids = set(re.findall(r"(?mi)^\s*Submitted batch job ([1-9][0-9]{0,19})\s*$", output))
                if len(ids) == 1:
                    job, state = ids.pop(), "queued"
                elif pre_submit_failure(output):
                    state = "failed"
                    detail = "上传失败：TACC 远端空间不足" if "No space left on device" in output else "TCloud 提交失败：" + pre_submit_failure(output)[0]
                else:
                    _, remote = transport.cli("cat", f"model-{generation}.id")
                    ids = [line.strip() for line in remote.splitlines() if JOB_ID.fullmatch(line.strip())]
                    if len(ids) == 1:
                        job, state = ids[0], "queued"
                    else:
                        state, detail = "unconfirmed", "提交回执未确认，正在等待远端作业标识。请核对 TCloud 队列。"
            elif not transport.queued(job):
                state = "stopped" if stopping or state == "ready" else "failed"
                if state == "failed":
                    detail = f"作业在就绪前结束，请检查 slurm_log/qwen-public-serve-agent-{job}.log"
            elif stopping:
                code, output = transport.cli("cancel", "-j", job)
                if code or "[Tcloud Error]" in output:
                    detail = "正在核对取消结果"
            else:
                code, log = transport.cli("cat", f"slurm_log/qwen-public-serve-agent-{job}.log")
                if not code and "[Tcloud Error]" not in log:
                    if "VERIFY_STARTED_AT=" in log:
                        state = "loading"
                    address = re.search(r"(?m)^AGENT_BASE_URL=(http://[a-zA-Z0-9.-]+:8000/v1)\s*$", log)
                    if address and all(mark in log for mark in READY):
                        state, url = "ready", address[1]
                elif state in {"ready", "unreachable"}:
                    state = "unreachable"
                    detail = "暂时无法读取服务日志"
        except (OSError, TransportError) as exc:
            detail = "暂时无法连接 TCloud，稍后重新检查"
            if state == "ready":
                state = "unreachable"
            if state == "requested":
                if isinstance(exc, TransportError) and exc.code == "AGENT_TCLOUD_UNAVAILABLE":
                    state, detail = "failed", "找不到 TCloud CLI"
                else:
                    state = "unconfirmed"
        with sessions.begin() as session:
            row = session.get(CourseService, 1, with_for_update=True)
            if row.generation != generation:
                return
            row.state, row.job_id, row.detail = state, job, detail
            if state != "ready" or url:
                row.base_url = url
            if state in {"stopped", "failed"}:
                row.stop_requested = False
            row.checked_at = datetime.now(UTC)


def monitor(sessions, transport, stop):
    directory = transport.settings.resolved_agent_exchange_root / "model-service"
    while not stop.is_set():
        try:
            reconcile(sessions, transport, directory)
        except TimeoutError:
            pass  # Another worker is reconciling this job.
        except Exception:
            logger.exception("Course model service check deferred")
        stop.wait(5)
