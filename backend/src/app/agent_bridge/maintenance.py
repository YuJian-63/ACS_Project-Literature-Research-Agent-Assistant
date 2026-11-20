import argparse
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select, text

from app.agent_bridge.bundles import (
    canonical_json,
    exchange_directory,
    manifest_digest,
    read_json,
)
from app.agent_bridge.contracts import DispatchManifest
from app.agent_bridge.files import atomic_write, controlled
from app.agent_bridge.transport import Transport, create_transport, transport_name
from app.config import Settings
from app.db.models import AgentRun, Task
from app.db.session import create_database_engine, create_session_factory
from app.tasks.lifecycle import append_event, database_time, locked_task

logger = logging.getLogger(__name__)


def remove_retained_directory(
    directory: Path,
    receipt: Path,
    retention_seconds: int,
    *,
    apply: bool = False,
    terminal_time: float | None = None,
) -> bool:
    directory, receipt = controlled(directory), controlled(receipt)
    external = (
        receipt.parent.name == "retired"
        and receipt.name == directory.name + ".json"
        and receipt.parent.parent == directory.parent.parent
        and directory.parent.name == "jobs"
    )
    if (
        str(UUID(directory.name)) != directory.name
        or receipt.parent != directory
        and not external
        or retention_seconds < 86400
    ):
        raise ValueError(
            "Cleanup requires an isolated dispatch directory and retention"
        )
    if (
        time.time()
        - (receipt.stat().st_mtime if terminal_time is None else terminal_time)
        < retention_seconds
    ):
        return False
    for current, directories, files in os.walk(directory, followlinks=False):
        for name in directories + files:
            target = controlled(Path(current) / name)
            if not target.is_dir() and not target.is_file():
                raise ValueError("Unexpected cleanup entry")
    if apply:
        shutil.rmtree(directory)
    return True


def cancel_terminal(
    sessions, settings: Settings, task_id: UUID, transport: Transport
) -> bool:
    with sessions() as session:
        task, run = session.get(Task, task_id), session.get(AgentRun, task_id)
        if (
            task is None
            or run is None
            or task.status != "failed"
            or run.result is not None
            or task.run_config.get("agent_cancel_confirmed")
        ):
            return False
        if (
            task.run_config.get("transport", "file-exchange-v1")
            != transport_name(settings)
            or settings.agent_transport == "manual"
        ):
            return False
        manifest = DispatchManifest.model_validate(run.manifest)
        if (
            manifest.dispatch_id != run.dispatch_id
            or manifest_digest(manifest) != run.input_sha256
        ):
            raise ValueError("Terminal dispatch identity changed")
        job_id = run.remote_job_id
    confirmed = transport.cancel(manifest, job_id)
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        run = session.get(AgentRun, task_id)
        if (
            task is None
            or run is None
            or task.status != "failed"
            or run.dispatch_id != manifest.dispatch_id
            or run.result is not None
        ):
            return False
        now = database_time(session)
        run.updated_at = now
        if confirmed and not task.run_config.get("agent_cancel_confirmed"):
            task.run_config = {**task.run_config, "agent_cancel_confirmed": True}
            append_event(session, task, now, "已确认 Agent 作业停止或尚未提交", "stage")
    return confirmed


class AgentMaintenance:
    def __init__(self, sessions, settings: Settings):
        self.sessions, self.settings = sessions, settings
        self.transport = create_transport(settings)
        self.stopped = threading.Event()
        self.thread = threading.Thread(
            target=self.run, name="agent-maintenance", daemon=True
        )

    def sweep(self) -> None:
        if self.settings.agent_transport == "manual":
            return
        with self.sessions() as session:
            candidates = list(
                session.scalars(
                    select(AgentRun.task_id)
                    .join(Task, Task.id == AgentRun.task_id)
                    .where(
                        Task.status == "failed",
                        Task.runner_type == "agent",
                        AgentRun.result.is_(None),
                        func.coalesce(
                            Task.run_config["transport"].as_string(), "file-exchange-v1"
                        )
                        == transport_name(self.settings),
                        Task.run_config["agent_cancel_confirmed"]
                        .as_boolean()
                        .is_not(True),
                    )
                    .order_by(AgentRun.updated_at, AgentRun.task_id)
                    .limit(100)
                )
            )
        for task_id in candidates:
            if self.stopped.is_set():
                break
            try:
                cancel_terminal(self.sessions, self.settings, task_id, self.transport)
            except Exception:
                logger.warning("Agent cancellation pending: task_id=%s", task_id)
                with self.sessions.begin() as session:
                    run = session.get(AgentRun, task_id)
                    if run is not None:
                        run.updated_at = database_time(session)

    def run(self) -> None:
        while not self.stopped.is_set():
            try:
                self.sweep()
            except Exception:
                logger.warning(
                    "Agent maintenance deferred; database or transport unavailable"
                )
            self.stopped.wait(10)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stopped.set()
        self.thread.join()


def cleanup_completed(
    sessions, settings: Settings, *, apply: bool = False, limit: int = 100
) -> list[dict]:
    transport = create_transport(settings)
    with sessions() as session:
        rows = session.execute(
            select(Task, AgentRun)
            .join(AgentRun, AgentRun.task_id == Task.id)
            .where(
                Task.status.in_(["succeeded", "failed"]),
                Task.runner_type == "agent",
                func.coalesce(
                    Task.run_config["transport"].as_string(), "file-exchange-v1"
                )
                == transport_name(settings),
                Task.finished_at
                + literal(settings.agent_retention_seconds)
                * text("interval '1 second'")
                <= func.clock_timestamp(),
                or_(
                    AgentRun.result.is_not(None),
                    Task.status == "succeeded",
                    and_(
                        Task.status == "failed",
                        Task.run_config["agent_cancel_confirmed"]
                        .as_boolean()
                        .is_(True),
                    ),
                ),
                Task.run_config["agent_files_removed"].as_boolean().is_not(True),
            )
            .order_by(AgentRun.updated_at, Task.id)
            .limit(limit)
        ).all()
    reports = []
    for task, run in rows:
        with sessions.begin() as session:
            current_run = session.get(AgentRun, task.id)
            if current_run is not None:
                current_run.updated_at = database_time(session)
        try:
            report = cleanup_run(sessions, settings, transport, task, run, apply=apply)
            if report is not None:
                reports.append(report)
        except (OSError, ValueError, RuntimeError):
            logger.warning("Agent cleanup pending: task_id=%s", task.id)
            reports.append(
                {
                    "task_id": str(task.id),
                    "dispatch_id": str(run.dispatch_id),
                    "removed": False,
                    "error": "AGENT_CLEANUP_PENDING",
                }
            )
    return reports


def cleanup_run(
    sessions,
    settings: Settings,
    transport: Transport,
    task: Task,
    run: AgentRun,
    *,
    apply: bool,
) -> dict | None:
    manifest = DispatchManifest.model_validate(run.manifest)
    if (
        manifest.dispatch_id != run.dispatch_id
        or manifest_digest(manifest) != run.input_sha256
    ):
        raise ValueError("Cleanup dispatch identity changed")
    remote = transport.cleanup(manifest, run.remote_job_id, apply=apply)
    if settings.agent_transport != "manual" and not remote:
        return None
    eligible = True
    for area in ("outbox", "inbox", "jobs"):
        directory = exchange_directory(
            settings.resolved_agent_exchange_root, area, manifest.dispatch_id
        )
        if not directory.exists():
            continue
        marker = directory / "retained.json"
        expected = {
            "dispatch_id": str(manifest.dispatch_id),
            "input_sha256": run.input_sha256,
        }
        if marker.exists():
            if read_json(marker, 65536) != expected:
                raise ValueError("Cleanup marker identity changed")
        else:
            atomic_write(marker, canonical_json(expected))
            os.utime(marker, (task.finished_at.timestamp(),) * 2)
        eligible = (
            remove_retained_directory(
                directory, marker, settings.agent_retention_seconds, apply=apply
            )
            and eligible
        )
    if apply and eligible:
        with sessions.begin() as session:
            current = locked_task(session, task.id)
            if current is not None and current.status in {"succeeded", "failed"}:
                current.run_config = {**current.run_config, "agent_files_removed": True}
    return {
        "task_id": str(task.id),
        "dispatch_id": str(run.dispatch_id),
        "removed": apply and eligible,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile failed jobs or clean retained Agent exchange files"
    )
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument(
        "--apply", action="store_true", help="Delete eligible files; default is dry run"
    )
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.apply and not args.cleanup or not 1 <= args.limit <= 1000:
        parser.error("--apply requires --cleanup; --limit must be 1..1000")
    settings = Settings()
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    try:
        if args.cleanup:
            import json

            print(
                json.dumps(
                    cleanup_completed(
                        sessions, settings, apply=args.apply, limit=args.limit
                    )
                )
            )
        else:
            AgentMaintenance(sessions, settings).sweep()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
