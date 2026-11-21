import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

from app.agent_bridge.bundles import (
    canonical_json,
    exchange_directory,
    manifest_digest,
    read_json,
    read_result,
)
from app.agent_bridge.contracts import DispatchManifest
from app.agent_bridge.files import atomic_copy, atomic_write, controlled, dispatch_lock
from app.agent_bridge.results import validate_delivery
from app.agent_bridge.status import JobStatus, read_status
from app.config import Settings

MAX_INPUT_BYTES = 423 * 1024 * 1024


class TransportError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class Transport(Protocol):
    def upload(self, manifest: DispatchManifest, bundle: Path) -> None: ...
    def submit(
        self,
        manifest: DispatchManifest,
        previous_job_id: str | None = None,
        *,
        deadline: float | None = None,
    ) -> str | None: ...
    def poll(
        self, manifest: DispatchManifest, job_id: str | None
    ) -> JobStatus | None: ...
    def download(
        self, manifest: DispatchManifest, job_id: str | None
    ) -> Path | None: ...
    def cancel(self, manifest: DispatchManifest, job_id: str | None) -> bool: ...
    def cleanup(
        self, manifest: DispatchManifest, job_id: str | None, *, apply: bool = False
    ) -> bool: ...


class ManualTransport:
    def __init__(self, settings: Settings):
        self.settings = settings

    def directory(self, manifest: DispatchManifest) -> Path:
        return exchange_directory(
            self.settings.resolved_agent_exchange_root, "inbox", manifest.dispatch_id
        )

    def upload(self, manifest: DispatchManifest, bundle: Path) -> None:
        pass

    def submit(
        self,
        manifest: DispatchManifest,
        previous_job_id: str | None = None,
        *,
        deadline: float | None = None,
    ) -> str | None:
        return previous_job_id

    def poll(self, manifest: DispatchManifest, job_id: str | None) -> JobStatus | None:
        target = self.directory(manifest) / "status.json"
        return (
            read_status(target, manifest, job_id)
            if target.exists() or target.is_symlink()
            else None
        )

    def download(self, manifest: DispatchManifest, job_id: str | None) -> Path | None:
        target = self.directory(manifest) / "result.json"
        if not target.exists() and not target.is_symlink():
            return None
        envelope = read_result(target, self.settings.agent_result_max_bytes)
        validate_delivery(manifest, envelope)
        if job_id is not None and envelope.remote_job_id != job_id:
            raise ValueError("Result belongs to another job")
        return target

    def cancel(self, manifest: DispatchManifest, job_id: str | None) -> bool:
        return False

    def cleanup(
        self, manifest: DispatchManifest, job_id: str | None, *, apply: bool = False
    ) -> bool:
        return False


class LocalTransport(ManualTransport):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        if settings.agent_local_root is None or settings.agent_local_python is None:
            raise ValueError(
                "Local transport requires AGENT_LOCAL_ROOT and AGENT_LOCAL_PYTHON"
            )
        base = Path(__file__).resolve().parents[3]
        self.agent_root = controlled(
            Path(os.path.abspath(base / settings.agent_local_root))
        )
        self.python = Path(os.path.abspath(base / settings.agent_local_python))
        if (
            not self.agent_root.is_dir()
            or not (self.agent_root / "run_dispatch.py").is_file()
            or not self.python.is_file()
        ):
            raise ValueError("Local Agent directory or interpreter is unavailable")

    def directory(self, manifest: DispatchManifest) -> Path:
        return exchange_directory(
            self.settings.resolved_agent_exchange_root, "jobs", manifest.dispatch_id
        )

    def retired(self, manifest: DispatchManifest) -> Path:
        return controlled(
            self.settings.resolved_agent_exchange_root
            / "retired"
            / (str(manifest.dispatch_id) + ".json")
        )

    def is_retired(self, manifest: DispatchManifest) -> bool:
        target = self.retired(manifest)
        if not target.exists():
            return False
        value = read_json(target, 65536)
        if (
            value.get("dispatch_id") != str(manifest.dispatch_id)
            or value.get("input_sha256") != manifest_digest(manifest)
            or type(value.get("terminal_at")) not in {int, float}
            or not math.isfinite(value["terminal_at"])
        ):
            raise ValueError("Retired dispatch identity changed")
        return True

    def upload(self, manifest: DispatchManifest, bundle: Path) -> None:
        if self.is_retired(manifest):
            raise TransportError("AGENT_DISPATCH_RETIRED")
        atomic_copy(bundle, self.directory(manifest) / "input.zip", MAX_INPUT_BYTES)

    def submit(
        self,
        manifest: DispatchManifest,
        previous_job_id: str | None = None,
        *,
        deadline: float | None = None,
    ) -> str:
        if self.is_retired(manifest):
            raise TransportError("AGENT_DISPATCH_RETIRED")
        try:
            with dispatch_lock(self.directory(manifest)):
                return self._submit_locked(manifest, previous_job_id, deadline)
        except TimeoutError:
            raise TransportError("AGENT_SUBMISSION_BUSY", retryable=True) from None

    def _submit_locked(
        self,
        manifest: DispatchManifest,
        previous_job_id: str | None,
        deadline: float | None,
    ) -> str:
        if self.is_retired(manifest):
            raise TransportError("AGENT_DISPATCH_RETIRED")
        directory = self.directory(manifest)
        if (directory / "cancel.request").exists():
            raise TransportError("AGENT_PROCESS_CANCELLED")
        job_id = f"local:{manifest.dispatch_id}"
        identity = {
            "dispatch_id": str(manifest.dispatch_id),
            "input_sha256": manifest_digest(manifest),
            "remote_job_id": job_id,
        }
        target = directory / "submission.json"
        if previous_job_id is not None and previous_job_id != job_id:
            raise ValueError("Saved local job identity changed")
        if target.exists():
            record = read_json(target, 65536)
            if any(record.get(key) != value for key, value in identity.items()):
                raise ValueError("Local submission identity changed")
            return job_id
        if previous_job_id is not None:
            raise TransportError("AGENT_SUBMISSION_UNCERTAIN")
        if deadline is None:
            deadline = time.time() + manifest.task.timeout_seconds
        if type(deadline) not in {int, float} or not math.isfinite(deadline):
            raise ValueError("Invalid execution deadline")
        if deadline <= time.time():
            raise TransportError("AGENT_PROCESS_TIMEOUT")
        try:
            descriptor = os.open(
                controlled(directory / ".submit.lock"),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            raise TransportError("AGENT_SUBMISSION_UNCERTAIN") from None
        os.close(descriptor)
        record = {
            "schema_version": "agent-local-submission-v1",
            **identity,
            "python": str(self.python),
            "agent_root": str(self.agent_root),
            "timeout_seconds": manifest.task.timeout_seconds,
            "deadline": deadline,
            "max_result_bytes": self.settings.agent_result_max_bytes,
        }
        atomic_write(target, canonical_json(record))
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "app.agent_bridge.local_job",
                    "--spec",
                    str(target),
                ],
                cwd=Path(__file__).resolve().parents[3],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **(
                    {
                        "creationflags": subprocess.CREATE_NO_WINDOW
                        | subprocess.CREATE_NEW_PROCESS_GROUP
                    }
                    if os.name == "nt"
                    else {"start_new_session": True}
                ),
            )
            threading.Thread(
                target=process.wait, name="agent-local-reaper", daemon=True
            ).start()
        except OSError:
            atomic_write(
                directory / "exit.json",
                canonical_json(
                    {
                        "schema_version": "agent-local-exit-v1",
                        **identity,
                        "returncode": None,
                        "error": "AGENT_LAUNCH_FAILED",
                    }
                ),
            )
            raise TransportError("AGENT_LAUNCH_FAILED") from None
        return job_id

    def poll(self, manifest: DispatchManifest, job_id: str | None) -> JobStatus | None:
        status = super().poll(manifest, job_id)
        receipt = self.directory(manifest) / "exit.json"
        if receipt.exists():
            value = read_json(receipt, 65536)
            if (
                value.get("schema_version") != "agent-local-exit-v1"
                or value.get("dispatch_id") != str(manifest.dispatch_id)
                or value.get("input_sha256") != manifest_digest(manifest)
                or value.get("remote_job_id") != job_id
            ):
                raise ValueError("Local exit identity changed")
            error = value.get("error")
            if error is not None:
                if error not in {
                    "AGENT_LAUNCH_FAILED",
                    "AGENT_PROCESS_TIMEOUT",
                    "AGENT_PROCESS_CANCELLED",
                }:
                    raise ValueError("Unknown local exit error")
                raise TransportError(error)
            if not (self.directory(manifest) / "result.json").exists() and (
                status is None or status.state == "running"
            ):
                raise TransportError(
                    "AGENT_PROCESS_FAILED"
                    if value.get("returncode")
                    else "AGENT_RESULT_MISSING"
                )
        return status

    def download(self, manifest: DispatchManifest, job_id: str | None) -> Path | None:
        target = super().download(manifest, job_id)
        if target is None:
            return None
        incoming = (
            exchange_directory(
                self.settings.resolved_agent_exchange_root,
                "inbox",
                manifest.dispatch_id,
            )
            / "result.json"
        )
        atomic_copy(target, incoming, self.settings.agent_result_max_bytes)
        return incoming

    def cancel(self, manifest: DispatchManifest, job_id: str | None) -> bool:
        if self.is_retired(manifest):
            return True
        try:
            with dispatch_lock(self.directory(manifest)):
                return self._cancel_locked(manifest, job_id)
        except TimeoutError:
            return False

    def _cancel_locked(self, manifest: DispatchManifest, job_id: str | None) -> bool:
        directory = self.directory(manifest)
        identity = {
            "dispatch_id": str(manifest.dispatch_id),
            "input_sha256": manifest_digest(manifest),
        }
        atomic_write(directory / "cancel.request", canonical_json(identity))
        if not (directory / "submission.json").exists():
            return not (directory / ".submit.lock").exists()
        value = read_json(directory / "submission.json", 65536)
        if (
            any(value.get(key) != item for key, item in identity.items())
            or job_id is not None
            and value.get("remote_job_id") != job_id
        ):
            raise ValueError("Cancelled submission identity changed")
        if (directory / "exit.json").exists():
            return True
        return False

    def cleanup(
        self, manifest: DispatchManifest, job_id: str | None, *, apply: bool = False
    ) -> bool:
        from app.agent_bridge.maintenance import remove_retained_directory

        directory = self.directory(manifest)
        receipt = directory / "exit.json"
        if self.is_retired(manifest):
            if directory.exists():
                marker = self.retired(manifest)
                return remove_retained_directory(
                    directory,
                    marker,
                    self.settings.agent_retention_seconds,
                    apply=apply,
                    terminal_time=read_json(marker, 65536)["terminal_at"],
                )
            return True
        if not receipt.exists():
            receipt = directory / "cancel.request"
            if (
                not receipt.exists()
                or (directory / ".submit.lock").exists()
                or job_id is not None
            ):
                return False
        value = read_json(receipt, 65536)
        if (
            value.get("dispatch_id") != str(manifest.dispatch_id)
            or value.get("input_sha256") != manifest_digest(manifest)
            or receipt.name == "exit.json"
            and (
                value.get("schema_version") != "agent-local-exit-v1"
                or value.get("remote_job_id") != job_id
            )
        ):
            raise ValueError("Cleanup receipt identity changed")
        if apply and remove_retained_directory(
            directory, receipt, self.settings.agent_retention_seconds
        ):
            identity = {
                "dispatch_id": str(manifest.dispatch_id),
                "input_sha256": manifest_digest(manifest),
                "terminal_at": receipt.stat().st_mtime,
            }
            atomic_write(self.retired(manifest), canonical_json(identity))
        return remove_retained_directory(
            directory, receipt, self.settings.agent_retention_seconds, apply=apply
        )


def create_transport(settings: Settings) -> Transport:
    if settings.agent_transport == "local":
        return LocalTransport(settings)
    if settings.agent_transport == "tacc":
        from app.agent_bridge.tacc import TaccTransport

        return TaccTransport(settings)
    return ManualTransport(settings)


def transport_name(settings: Settings) -> str:
    return {
        "manual": "file-exchange-v1",
        "local": "local-process-v1",
        "tacc": "tacc-ssh-slurm-v1",
    }[settings.agent_transport]
