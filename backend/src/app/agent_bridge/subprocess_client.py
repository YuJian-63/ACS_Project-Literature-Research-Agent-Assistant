"""Bounded, cancellable file protocol for the isolated Agent process."""

import json
import math
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

BRIDGE_SCRIPT = Path(__file__).with_name("bridge.py")
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
POLL_SECONDS = 0.05


class AgentProcessError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _terminate(process):
    # Signal the whole session even when the leader has already exited.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS may deny a group signal after the process has exited.
            if process.poll() is None:
                try:
                    process.send_signal(sig)
                except ProcessLookupError:
                    pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        if sig == signal.SIGTERM:
            # Descendants can outlive the leader; always follow with group KILL.
            continue
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass


def run_agent(
    task: dict, *, python: str, timeout_seconds: float, stopped: Callable[[], bool]
) -> dict:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise AgentProcessError("agent_timeout", "Agent deadline exceeded")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="agent-v1-") as directory:
        root = Path(directory)
        request, result, log = (
            root / name for name in ("task.json", "result.json", "process.log")
        )
        request.write_text(json.dumps(task), encoding="utf-8")
        process = None
        try:
            with log.open("wb") as diagnostics:
                try:
                    process = subprocess.Popen(
                        [python, str(BRIDGE_SCRIPT), str(request), str(result)],
                        stdin=subprocess.DEVNULL,
                        stdout=diagnostics,
                        stderr=diagnostics,
                        start_new_session=True,
                    )
                except OSError as exc:
                    raise AgentProcessError(
                        "agent_unavailable", "Agent interpreter could not be started"
                    ) from exc
                while True:
                    if stopped():
                        raise AgentProcessError(
                            "agent_cancelled", "Agent execution stopped"
                        )
                    if time.monotonic() - started >= timeout_seconds:
                        raise AgentProcessError(
                            "agent_timeout", "Agent deadline exceeded"
                        )
                    if log.stat().st_size > MAX_LOG_BYTES or (
                        result.exists() and result.stat().st_size > MAX_RESULT_BYTES
                    ):
                        raise AgentProcessError(
                            "agent_output_limit", "Agent output exceeded its size limit"
                        )
                    if process.poll() is not None:
                        break
                    time.sleep(POLL_SECONDS)
                _terminate(process)
                if process.returncode:
                    raise AgentProcessError(
                        "agent_process_failed", "Agent process exited unsuccessfully"
                    )
                try:
                    # Bounded read also protects against a descendant writing after leader exit.
                    with result.open("rb") as stream:
                        raw = stream.read(MAX_RESULT_BYTES + 1)
                    if len(raw) > MAX_RESULT_BYTES:
                        raise AgentProcessError(
                            "agent_output_limit", "Agent output exceeded its size limit"
                        )
                    payload = json.loads(raw)
                except (OSError, ValueError, UnicodeError) as exc:
                    raise AgentProcessError(
                        "agent_invalid_result", "Agent did not return valid JSON"
                    ) from exc
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("task_id"), str
                ):
                    raise AgentProcessError(
                        "agent_invalid_result", "Agent result requires a task ID"
                    )
                if payload["task_id"] != task.get("task_id"):
                    raise AgentProcessError(
                        "agent_task_mismatch", "Agent result belongs to another task"
                    )
                if stopped():
                    raise AgentProcessError(
                        "agent_cancelled", "Agent execution stopped"
                    )
                if time.monotonic() - started >= timeout_seconds:
                    raise AgentProcessError("agent_timeout", "Agent deadline exceeded")
                return payload
        finally:
            if process is not None:
                _terminate(process)
