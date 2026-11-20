import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import test_agent_bridge as bridge_tests
from app.agent_bridge.bundles import manifest_digest
from app.agent_bridge.maintenance import (
    AgentMaintenance,
    cleanup_completed,
    cleanup_run,
    remove_retained_directory,
)
from app.config import Settings
from sqlalchemy.dialects import postgresql


class AgentMaintenanceTests(unittest.TestCase):
    def test_cleanup_reentry_accepts_already_removed_local_directories(self):
        fixture = bridge_tests.AgentBridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        task = SimpleNamespace(
            id=fixture.manifest.task.task_id,
            finished_at=datetime.now(timezone.utc),
            status="succeeded",
            run_config={},
        )
        run = SimpleNamespace(
            manifest=fixture.manifest.model_dump(mode="json"),
            dispatch_id=fixture.manifest.dispatch_id,
            input_sha256=manifest_digest(fixture.manifest),
            remote_job_id="8123",
        )
        transport = MagicMock()
        transport.cleanup.return_value = True
        result = cleanup_run(
            MagicMock(), fixture.settings, transport, task, run, apply=False
        )
        self.assertIsNotNone(result)
        self.assertFalse(result["removed"])

    def test_sql_filters_transport_before_limit_for_cancellation_and_cleanup(self):
        settings = Settings(
            _env_file=None, database_url="postgresql://unused:unused@127.0.0.1/unused"
        )
        sessions = MagicMock()
        session = sessions.return_value.__enter__.return_value
        session.scalars.return_value = []
        AgentMaintenance(
            sessions, settings.model_copy(update={"agent_transport": "manual"})
        ).sweep()
        maintenance = AgentMaintenance(sessions, settings)
        maintenance.settings = settings.model_copy(update={"agent_transport": "local"})
        maintenance.sweep()
        query = str(
            session.scalars.call_args.args[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("local-process-v1", query.split("LIMIT")[0])
        session.execute.return_value.all.return_value = []
        cleanup_completed(sessions, settings)
        query = str(
            session.execute.call_args.args[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("file-exchange-v1", query.split("LIMIT")[0])
        self.assertIn("finished_at", query.split("LIMIT")[0])

    def test_cleanup_defaults_to_dry_run_and_requires_retention(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve() / str(uuid4())
            directory.mkdir()
            receipt = directory / "exit.json"
            receipt.write_text("{}")
            self.assertFalse(remove_retained_directory(directory, receipt, 86400))
            os.utime(receipt, (time.time() - 90000,) * 2)
            self.assertTrue(remove_retained_directory(directory, receipt, 86400))
            self.assertTrue(directory.exists())
            self.assertTrue(
                remove_retained_directory(directory, receipt, 86400, apply=True)
            )
            self.assertFalse(directory.exists())

    def test_cleanup_rejects_non_dispatch_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            receipt = directory / "exit.json"
            receipt.write_text("{}")
            with self.assertRaises(ValueError):
                remove_retained_directory(directory, receipt, 86400, apply=True)
