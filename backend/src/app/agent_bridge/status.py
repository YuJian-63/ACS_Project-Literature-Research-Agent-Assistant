from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.agent_bridge.bundles import manifest_digest, read_json
from app.agent_bridge.contracts import Contract, DispatchManifest, StopReason


class JobError(Contract):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    type: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$")


class JobStatus(Contract):
    schema_version: Literal["agent-job-status-v1"]
    dispatch_id: UUID
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    remote_job_id: str | None = Field(default=None, min_length=1, max_length=256)
    state: Literal["running", "succeeded", "failed", "finished"]
    stop_reason: StopReason | None = None
    error: JobError | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def consistent_state(self):
        if self.updated_at.tzinfo is None:
            raise ValueError("Status timestamp must include timezone")
        if self.state == "running" and (
            self.stop_reason is not None or self.error is not None
        ):
            raise ValueError("Running status cannot contain an outcome")
        if self.state == "succeeded" and (
            self.stop_reason not in {"completed", "partial"} or self.error
        ):
            raise ValueError("Success requires a successful research outcome")
        if self.state == "failed" and (
            self.stop_reason in {"completed", "partial"}
            or (self.stop_reason is None) == (self.error is None)
        ):
            raise ValueError("Failure requires one research or wrapper outcome")
        if self.state == "finished" and (self.stop_reason is None or self.error):
            raise ValueError("Legacy status requires a research outcome")
        return self


def read_status(
    path: Path, manifest: DispatchManifest, job_id: str | None = None
) -> JobStatus:
    status = JobStatus.model_validate(read_json(path, 65536))
    if (
        status.dispatch_id != manifest.dispatch_id
        or status.input_sha256 != manifest_digest(manifest)
    ):
        raise ValueError("Status belongs to another dispatch")
    if job_id is not None and status.remote_job_id != job_id:
        raise ValueError("Status belongs to another job")
    return status
