import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

from app.agent_bridge.bundles import canonical_json, exchange_directory, manifest_digest, read_json, read_result
from app.agent_bridge.files import atomic_copy, atomic_write, controlled, dispatch_lock
from app.agent_bridge.results import validate_delivery
from app.agent_bridge.status import read_status
from app.agent_bridge.transport import ManualTransport, TransportError
from app.config import Settings

ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = ("tuxiv.conf", "job.sh", "run_job.py", "runtime.sh", "requirements.txt")
AGENT = ("baseline.py", "config.py", "context.py", "schemas.py", "apis/__init__.py",
    "apis/database.py", "apis/library.py", "apis/model.py", "apis/papers.py", "apis/search_web.py")
JOB_ID = re.compile(r"[1-9][0-9]{0,19}")


def submit_progress(output: str) -> str:
    if "sbatch" in output or "dependencies updated." in output or "Successfully create environment " in output:
        return "scheduler"
    if any(marker in output.lower() for marker in ("solving environment", "collecting package", "transaction", "conda env")):
        return "environment"
    if any(marker in output for marker in ("Transfer starting:", "sending incremental file list", "configurations/run.slurm", "rsync:")):
        return "upload"
    return "preparation" if "Start parsing tuxiv.conf" in output else "connection"


def pre_submit_failure(output: str):
    # SDK 0.4.1 aborts on these messages before its sole sbatch call. Other errors, including
    # a lost SSH connection during sbatch, do not establish whether the scheduler accepted it.
    lines = re.findall(r"(?m)^\[Tcloud Error\] [^\r\n]*? (?:tcloudcli|tuxivconfig)\.go:\d+: ([^\r\n]+)", output)
    if not lines:
        return None
    last = lines[-1].strip()
    if last in {"Failed to create remote session", "Failed to create remote workdir", "Failed to create remote userdir"}:
        return "connection", True
    if last == "Failed to upload env repository":
        return "upload", True
    if last == "Failed to create conda env" or last.startswith("Failed to update "):
        return "environment", False
    if last in {"Failed to parse tuxiv.conf", "Failed to add softlink", "Failed to remove all auto-generated files"} or last.startswith("Fail to upload file. Upload size:"):
        return "preparation", False
    return None


def stage_model_env(path: Path, target: Path, deadline: float) -> None:
    with controlled(path).open("r", encoding="utf-8") as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size > 65536
            or os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077)):
            raise ValueError("The model environment file must be private to the Worker account")
        config = dotenv_values(stream=source, interpolate=False)
    base_url = config.get("MODEL_BASE_URL") or ""
    endpoint = urlsplit(base_url)
    host = endpoint.hostname or ""
    official = host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"} or re.fullmatch(
        r"[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com", host)
    if (not official or endpoint.scheme != "https" or endpoint.netloc != host or endpoint.query or endpoint.fragment
        or endpoint.path.rstrip("/") not in {"/compatible-mode/v1", "/v1"}):
        raise ValueError("Bailian temporary keys require an official HTTPS model endpoint")
    model = config.get("MODEL_NAME", "qwen3.8-27b")
    if (config.get("MODEL_PROVIDER", "bailian") != "bailian" or not config.get("BAILIAN_API_KEY")
        or not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", model)):
        raise ValueError("The course CPU job requires a configured Bailian endpoint and key")
    ttl = min(1800, int(deadline - time.time()))
    if ttl < 1:
        raise TransportError("AGENT_PROCESS_TIMEOUT")
    try:
        response = httpx.post(f"https://{host}/api/v1/tokens", params={"expire_in_seconds": ttl},
            headers={"Authorization": "Bearer " + config["BAILIAN_API_KEY"]}, timeout=15,
            follow_redirects=False, trust_env=False)
    except httpx.HTTPError:
        raise TransportError("AGENT_MODEL_TOKEN_UNREACHABLE", retryable=True) from None
    if response.status_code != 200:
        raise TransportError("AGENT_MODEL_TOKEN_REJECTED", retryable=response.status_code == 429 or response.status_code >= 500)
    try:
        body = response.json()
        token, expiry = body["token"], body["expires_at"]
    except (ValueError, TypeError, KeyError):
        raise TransportError("AGENT_MODEL_TOKEN_INVALID") from None
    now = time.time()
    if (not isinstance(token, str) or not re.fullmatch(r"st-[A-Za-z0-9_+.=/\-]{1,4096}", token)
        or token == config["BAILIAN_API_KEY"] or type(expiry) is not int or not now < expiry <= min(deadline, now + ttl) + 5):
        raise TransportError("AGENT_MODEL_TOKEN_INVALID")
    atomic_write(target, f"MODEL_PROVIDER=bailian\nMODEL_NAME={model}\nMODEL_BASE_URL={base_url}\nBAILIAN_API_KEY={token}\n".encode())


class TcloudTransport(ManualTransport):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        if not settings.agent_library_public_url:
            raise ValueError("Course jobs require AGENT_LIBRARY_PUBLIC_URL")
        self.missing_since = {}

    def jobs(self, manifest):
        return exchange_directory(self.settings.resolved_agent_exchange_root, "jobs", manifest.dispatch_id)

    def cli(self, *args, cwd=None, timeout=None):
        try:
            response = subprocess.run(
                [self.settings.agent_tcloud_cli, *args], cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                timeout=timeout if timeout is not None else self.settings.agent_transport_timeout_seconds,
            )
        except (FileNotFoundError, PermissionError):
            raise TransportError("AGENT_TCLOUD_UNAVAILABLE") from None
        except subprocess.TimeoutExpired as error:
            if args[0] == "submit":
                partial = error.stdout or b""
                return None, partial.decode("utf-8", errors="replace") if isinstance(partial, bytes) else partial
            raise TransportError("AGENT_TCLOUD_UNREACHABLE", retryable=True) from None
        except OSError:
            raise TransportError("AGENT_TCLOUD_UNREACHABLE", retryable=True) from None
        return response.returncode, response.stdout

    def stage(self, manifest, stage, deadline):
        outbox = exchange_directory(self.settings.resolved_agent_exchange_root, "outbox", manifest.dispatch_id)
        stage.mkdir(mode=0o700)
        for name in TEMPLATE:
            source = ROOT / "tacc" / "research" / name
            if name == "tuxiv.conf":
                content = source.read_text().replace("DISPATCH_ID", str(manifest.dispatch_id))
                (stage / name).write_text(content)
            else:
                shutil.copyfile(source, stage / name)
        (stage / "agent" / "apis").mkdir(parents=True)
        for name in AGENT:
            shutil.copyfile(ROOT / "agent" / name, stage / "agent" / name)
        shutil.copyfile(controlled(outbox / "input.zip"), stage / "input.zip")
        atomic_copy(outbox / "library-access.json", stage / "library-access.json", 65536)
        if self.settings.agent_tcloud_model_env_file:
            stage_model_env(self.settings.agent_tcloud_model_env_file, stage / "model.env", deadline)
        atomic_write(stage / "dispatch.json", canonical_json({
            "dispatch_id": str(manifest.dispatch_id), "input_sha256": manifest_digest(manifest), "deadline": deadline,
        }))

    def fetch(self, manifest, name, target):
        remote = f"acs-research/jobs/{manifest.dispatch_id}/{name}"
        code, output = self.cli("download", remote, str(target))
        if any(msg in output.lower() for msg in ("file does not exist", "no such file or directory", "file not found")):
            return False
        if code or "[Tcloud Error]" in output or not target.is_file():
            raise TransportError("AGENT_TCLOUD_DOWNLOAD", retryable=True)
        return True

    def remote_status(self, manifest, job_id):
        with tempfile.TemporaryDirectory(dir=self.jobs(manifest)) as directory:
            target = Path(directory) / "status.json"
            if not self.fetch(manifest, "status.json", target):
                return None
            status = read_status(target, manifest, job_id)
            if not JOB_ID.fullmatch(status.remote_job_id or ""):
                raise ValueError("Invalid tcloud job ID in status")
            return status

    def receipt(self, manifest):
        target = self.jobs(manifest) / "submission.json"
        if not target.exists():
            return None
        record = read_json(target, 65536)
        if record.get("dispatch_id") != str(manifest.dispatch_id) or record.get("input_sha256") != manifest_digest(manifest):
            raise ValueError("Saved tcloud dispatch identity changed")
        job_id = record["remote_job_id"]
        if job_id is not None and (not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id)):
            raise ValueError("Invalid saved tcloud job ID")
        return record

    def submit(self, manifest, previous_job_id=None, *, deadline=None):
        work = self.jobs(manifest)
        try:
            with dispatch_lock(work):
                if (work / "cancel.request").exists():
                    raise TransportError("AGENT_PROCESS_CANCELLED")
                record = self.receipt(manifest)
                if previous_job_id is not None:
                    if not JOB_ID.fullmatch(previous_job_id) or record and record["remote_job_id"] not in (None, previous_job_id):
                        raise ValueError("Platform job ID disagrees with the saved dispatch")
                    return previous_job_id
                if record is not None and record.get("outcome") != "not_submitted":
                    if record["remote_job_id"] is not None:
                        return record["remote_job_id"]
                    status = self.remote_status(manifest, None)
                    if status is None:
                        raise TransportError("AGENT_SUBMISSION_UNCERTAIN", retryable=True)
                    job_id = status.remote_job_id
                else:
                    if not deadline or deadline <= time.time():
                        raise TransportError("AGENT_PROCESS_TIMEOUT")
                    record = {"dispatch_id": str(manifest.dispatch_id), "input_sha256": manifest_digest(manifest),
                        "remote_job_id": None}
                    with tempfile.TemporaryDirectory(dir=work) as private:
                        stage = Path(private) / f"acs-{manifest.dispatch_id}"
                        self.stage(manifest, stage, deadline)
                        # A lost SSH/SDK reply can follow an accepted batch job. Record intent before submitting.
                        atomic_write(work / "submission.json", canonical_json(record))
                        started = time.monotonic()
                        timeout = min(self.settings.agent_tcloud_submit_timeout_seconds, deadline - time.time())
                        if timeout <= 0:
                            (work / "submission.json").unlink()
                            raise TransportError("AGENT_PROCESS_TIMEOUT")
                        try:
                            code, output = self.cli("submit", cwd=stage, timeout=timeout)
                        except TransportError as error:
                            if error.code == "AGENT_TCLOUD_UNAVAILABLE":
                                (work / "submission.json").unlink()
                            raise
                        # This SDK pads synchronized rsync output with NULs. Retain only bounded,
                        # non-sensitive diagnostics. Raw phase output can contain local paths.
                        output = output.replace("\0", "")
                        ids = set(re.findall(r"(?mi)^\s*Submitted batch job ([1-9][0-9]{0,19})\s*$", output))
                        if len(ids) != 1:
                            failure = pre_submit_failure(output) if code is not None and not ids else None
                            phase = failure[0] if failure else submit_progress(output)
                            reason = f"AGENT_TCLOUD_{phase.upper()}_FAILED" if failure else (
                                "timeout" if code is None else "missing_ack")
                            record.update(outcome="not_submitted" if failure else "uncertain",
                                phase=phase, exit_code=code, elapsed_seconds=round(time.monotonic() - started, 2),
                                error=reason)
                            atomic_write(work / "submission.json", canonical_json(record))
                            if failure:
                                raise TransportError(reason, retryable=failure[1])
                            raise TransportError("AGENT_SUBMISSION_UNCERTAIN", retryable=True)
                        job_id = ids.pop()
                record["remote_job_id"] = job_id
                record["outcome"] = "accepted"
                atomic_write(work / "submission.json", canonical_json(record))
                return job_id
        except TimeoutError:
            raise TransportError("AGENT_SUBMISSION_BUSY", retryable=True) from None

    def queued(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise ValueError("Missing or invalid platform job ID")
        code, output = self.cli("ps", "-j", job_id)
        if "Invalid job id specified" in output:
            return False
        if code or "[Tcloud Error]" in output or not re.search(r"(?m)^\s*JOBID\s", output):
            raise TransportError("AGENT_TCLOUD_QUERY", retryable=True)
        return bool(re.search(rf"(?m)^\s*{job_id}\s", output))

    def poll(self, manifest, job_id):
        # The preceding worker may have persisted the validated result just before its lease ended.
        if (self.directory(manifest) / "result.json").exists():
            return None
        if self.queued(job_id):
            self.missing_since.pop(job_id, None)
            return None
        status = self.remote_status(manifest, job_id)
        if status and status.state != "running":
            self.missing_since.pop(job_id, None)
            if status.error:
                return status
            with tempfile.TemporaryDirectory(dir=self.jobs(manifest)) as private:
                target = Path(private) / "result.json"
                if not self.fetch(manifest, "result.json", target):
                    raise TransportError("AGENT_RESULT_MISSING")
                envelope = read_result(target, self.settings.agent_result_max_bytes)
                validate_delivery(manifest, envelope)
                if envelope.remote_job_id != job_id or envelope.result.stop_reason != status.stop_reason:
                    raise ValueError("Result and job status disagree")
                atomic_copy(target, self.directory(manifest) / "result.json", self.settings.agent_result_max_bytes)
            return status
        # Allow queue and filesystem visibility to settle before declaring a lost result.
        now = time.monotonic()
        if now - self.missing_since.setdefault(job_id, now) < 30:
            return None
        self.missing_since.pop(job_id)
        raise TransportError("AGENT_RESULT_MISSING" if status is None else "AGENT_PLATFORM_FAILED")

    def cancel(self, manifest, job_id):
        work = self.jobs(manifest)
        try:
            with dispatch_lock(work):
                atomic_write(work / "cancel.request", b"cancel\n")
                record = self.receipt(manifest)
                saved = record["remote_job_id"] if record else None
                if job_id is not None and saved is not None and saved != job_id:
                    raise ValueError("Cancellation job ID differs from the submission")
                job_id = job_id or saved
                if job_id is None:
                    if record is None or record.get("outcome") == "not_submitted":
                        return True
                    status = self.remote_status(manifest, None)
                    if status is None:
                        return False
                    job_id = status.remote_job_id
                if not self.queued(job_id):
                    return True
                self.cli("cancel", "-j", job_id)
                # Confirm disappearance on the next reconciliation, including a lost cancel reply.
                return False
        except TimeoutError:
            return False
