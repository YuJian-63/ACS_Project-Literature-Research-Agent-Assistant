import base64
import binascii
import re
import shlex
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from app.agent_bridge.bundles import (
    canonical_json,
    exchange_directory,
    manifest_digest,
    read_json,
    read_result,
)
from app.agent_bridge.contracts import DispatchManifest
from app.agent_bridge.files import atomic_write
from app.agent_bridge.results import validate_delivery
from app.agent_bridge.status import JobStatus, read_status
from app.agent_bridge.transport import MAX_INPUT_BYTES, ManualTransport, TransportError
from app.config import Settings

TERMINAL_STATES = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "PREEMPTED",
    "BOOT_FAIL",
    "DEADLINE",
    "REVOKED",
}
ACTIVE_STATES = {
    "PENDING",
    "RUNNING",
    "CONFIGURING",
    "COMPLETING",
    "SUSPENDED",
    "RESIZING",
    "REQUEUED",
    "REQUEUE_FED",
    "REQUEUE_HOLD",
    "SIGNALING",
    "STAGE_OUT",
}
REMOTE_ERRORS = {
    "AGENT_SCHEDULER_UNAVAILABLE",
    "AGENT_SCHEDULER_RESPONSE_INVALID",
    "AGENT_SUBMISSION_UNCERTAIN",
    "AGENT_DUPLICATE_JOBS",
    "AGENT_JOB_UNKNOWN",
    "AGENT_REMOTE_INVALID",
    "AGENT_DISPATCH_RETIRED",
    "AGENT_PLATFORM_CANCELLED",
    "AGENT_PLATFORM_TIMEOUT",
    "AGENT_SUBMISSION_BUSY",
}


class TaccTransport(ManualTransport):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        if not settings.agent_tacc_host or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", settings.agent_tacc_host
        ):
            raise ValueError("TACC transport requires an SSH host alias")
        for path in (settings.agent_tacc_helper, settings.agent_tacc_config):
            if (
                not path
                or not PurePosixPath(path).is_absolute()
                or any(character in path for character in "\x00\r\n")
                or ".." in PurePosixPath(path).parts
            ):
                raise ValueError("TACC helper/config must be absolute remote paths")
        self.reports = {}
        if any(character in settings.agent_tacc_python for character in "\x00\r\n"):
            raise ValueError("Invalid remote bridge interpreter")

    def _rpc(
        self,
        manifest: DispatchManifest,
        operation: str,
        *,
        bundle: Path | None = None,
        **values,
    ) -> dict:
        request = {
            "op": operation,
            "dispatch_id": str(manifest.dispatch_id),
            "input_sha256": manifest_digest(manifest),
            "timeout_seconds": manifest.task.timeout_seconds,
            "max_result_bytes": self.settings.agent_result_max_bytes,
            **values,
        }
        if bundle is not None:
            request["size_bytes"] = bundle.stat().st_size
            if request["size_bytes"] > MAX_INPUT_BYTES:
                raise ValueError("Input bundle exceeds transport limit")
        command = [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            self.settings.agent_tacc_host,
            shlex.join(
                [
                    self.settings.agent_tacc_python,
                    self.settings.agent_tacc_helper,
                    "--config",
                    self.settings.agent_tacc_config,
                ]
            ),
        ]
        with tempfile.TemporaryFile() as outgoing, tempfile.TemporaryFile() as incoming:
            outgoing.write(canonical_json(request) + b"\n")
            if bundle is not None:
                with bundle.open("rb") as source:
                    while chunk := source.read(65536):
                        outgoing.write(chunk)
            outgoing.seek(0)
            try:
                subprocess.run(
                    command,
                    stdin=outgoing,
                    stdout=incoming,
                    stderr=subprocess.DEVNULL,
                    timeout=self.settings.agent_transport_timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise TransportError(
                    "AGENT_TRANSPORT_UNAVAILABLE", retryable=True
                ) from None
            limit = (self.settings.agent_result_max_bytes * 4 + 2) // 3 + 131072
            if incoming.tell() > limit:
                raise ValueError("Remote response exceeds size limit")
            incoming.seek(0)
            payload = incoming.read(limit + 1)
        if not payload:
            raise TransportError("AGENT_TRANSPORT_UNAVAILABLE", retryable=True)
        directory = exchange_directory(
            self.settings.resolved_agent_exchange_root, "jobs", manifest.dispatch_id
        )
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="rpc-", suffix=".part", dir=directory, delete=False
        ) as output:
            output.write(payload)
            temporary = Path(output.name)
        try:
            response = read_json(temporary, limit)
        finally:
            temporary.unlink(missing_ok=True)
        if (
            not isinstance(response, dict)
            or response.get("schema_version") != "agent-transport-v1"
            or type(response.get("ok")) is not bool
        ):
            raise ValueError("Invalid remote response")
        if not response["ok"]:
            error = response.get("error", {})
            if (
                error.get("code") not in REMOTE_ERRORS
                or type(error.get("retryable")) is not bool
            ):
                raise ValueError("Invalid remote error")
            raise TransportError(error["code"], retryable=error["retryable"])
        if (
            response.get("dispatch_id") != str(manifest.dispatch_id)
            or response.get("input_sha256") != manifest_digest(manifest)
            or not isinstance(response.get("data"), dict)
        ):
            raise ValueError("Remote response identity changed")
        return response["data"]

    def upload(self, manifest: DispatchManifest, bundle: Path) -> None:
        if self._rpc(manifest, "upload", bundle=bundle).get("uploaded") is not True:
            raise ValueError("Remote upload not acknowledged")

    def submit(
        self,
        manifest: DispatchManifest,
        previous_job_id: str | None = None,
        *,
        deadline: float | None = None,
    ) -> str:
        value = self._rpc(manifest, "submit", job_id=previous_job_id, deadline=deadline)
        job_id = value.get("job_id")
        if (
            not isinstance(job_id, str)
            or not re.fullmatch(r"[0-9]{1,20}", job_id)
            or (previous_job_id is not None and previous_job_id != job_id)
        ):
            raise ValueError("Invalid or changed platform job ID")
        return job_id

    def poll(self, manifest: DispatchManifest, job_id: str | None) -> JobStatus | None:
        value = self._rpc(manifest, "query", job_id=job_id)
        if (
            value.get("job_id") != job_id
            or value.get("platform_state") not in ACTIVE_STATES | TERMINAL_STATES
            or type(value.get("has_result")) is not bool
        ):
            raise ValueError("Invalid scheduler response")
        self.reports[str(manifest.dispatch_id)] = value
        status = value.get("status")
        if status is not None:
            target = (
                exchange_directory(
                    self.settings.resolved_agent_exchange_root,
                    "jobs",
                    manifest.dispatch_id,
                )
                / "status.json"
            )
            atomic_write(target, canonical_json(status))
            result = read_status(target, manifest, job_id)
        else:
            result = None
        if (
            not value["has_result"]
            and value["platform_state"] in TERMINAL_STATES
            and not (result and result.state == "failed")
        ):
            code = (
                "AGENT_RESULT_MISSING"
                if value["platform_state"] == "COMPLETED"
                else "AGENT_PLATFORM_TIMEOUT"
                if value["platform_state"] == "TIMEOUT"
                else "AGENT_PLATFORM_FAILED"
            )
            raise TransportError(code)
        return result

    def download(self, manifest: DispatchManifest, job_id: str | None) -> Path | None:
        report = self.reports.get(str(manifest.dispatch_id))
        if report is None:
            self.poll(manifest, job_id)
            report = self.reports[str(manifest.dispatch_id)]
        if not report["has_result"]:
            return None
        value = self._rpc(manifest, "fetch", job_id=job_id, file="result.json")
        try:
            content = base64.b64decode(value["content"], validate=True)
        except (KeyError, ValueError, binascii.Error, TypeError):
            raise ValueError("Invalid remote file encoding") from None
        if len(content) > self.settings.agent_result_max_bytes:
            raise ValueError("Remote result exceeds size limit")
        directory = exchange_directory(
            self.settings.resolved_agent_exchange_root, "jobs", manifest.dispatch_id
        )
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="result-", suffix=".part", dir=directory, delete=False
        ) as output:
            output.write(content)
            temporary = Path(output.name)
        try:
            envelope = read_result(temporary, self.settings.agent_result_max_bytes)
            validate_delivery(manifest, envelope)
            if envelope.remote_job_id != job_id:
                raise ValueError("Remote result belongs to another job")
            incoming = (
                exchange_directory(
                    self.settings.resolved_agent_exchange_root,
                    "inbox",
                    manifest.dispatch_id,
                )
                / "result.json"
            )
            if (
                incoming.exists()
                and read_result(incoming, self.settings.agent_result_max_bytes)
                != envelope
            ):
                raise ValueError("Existing result delivery changed")
            atomic_write(incoming, content)
            return incoming
        finally:
            temporary.unlink(missing_ok=True)

    def cancel(self, manifest: DispatchManifest, job_id: str | None) -> bool:
        value = self._rpc(manifest, "cancel", job_id=job_id)
        if type(value.get("cancelled")) is not bool:
            raise ValueError("Invalid cancellation acknowledgement")
        return value["cancelled"]

    def cleanup(
        self, manifest: DispatchManifest, job_id: str | None, *, apply: bool = False
    ) -> bool:
        value = self._rpc(manifest, "cleanup", job_id=job_id, apply=apply)
        if (
            type(value.get("eligible")) is not bool
            or type(value.get("removed")) is not bool
        ):
            raise ValueError("Invalid cleanup acknowledgement")
        return value["removed"] if apply else value["eligible"]
