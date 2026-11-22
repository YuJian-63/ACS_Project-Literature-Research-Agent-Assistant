import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent_bridge.course_service import reconcile
from app.api.model_services import SharedEndpointInput, change_service, models, remove_shared, save_shared
from app.db.models import CourseService, SharedModelEndpoint
from app.errors import APIError


class CourseServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        CourseService.__table__.create(engine)
        SharedModelEndpoint.__table__.create(engine)
        self.sessions = sessionmaker(engine)
        with self.sessions.begin() as db:
            db.add(CourseService(id=1, state="stopped"))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name).resolve()
        self.user = SimpleNamespace(id=uuid4())
        self.tcloud = Mock()
        settings = SimpleNamespace(task_runner="agent", agent_transport="tcloud", agent_dispatch_enabled=True,
            agent_tcloud_submit_timeout_seconds=180, agent_tcloud_model_env_file=None)
        self.tcloud.settings = settings
        self.request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings, sessions=self.sessions)))

    def check(self):
        with self.sessions.begin() as db:
            db.get(CourseService, 1).checked_at = None
        reconcile(self.sessions, self.tcloud, self.directory)
        return models(self.request, self.user)

    def test_duplicate_start_loading_ready_and_owner_stop_after_restart(self):
        for _ in range(2):
            change_service("start", self.request, self.user)
        self.tcloud.cli.return_value = (0, "Submitted batch job 8123\r\n")
        self.assertEqual(self.check()["job_id"], "8123")
        self.tcloud.cli.assert_called_once()
        self.tcloud.queued.return_value = True
        url = "http://10.0.0.2:8000/v1"
        log = "VERIFY_STARTED_AT=1\nAGENT_BASE_URL=" + url + "\n"
        self.tcloud.cli.return_value = (0, log)
        self.assertIsNone(self.check()["base_url"])
        self.tcloud.cli.return_value = (0, log + "RUNTIME_MODE=public\nAGENT_TELEMETRY_READY=qwen-agent-telemetry-v1\nApplication startup complete.\n")
        service = self.check()
        self.assertEqual((service["state"], service["base_url"]), ("ready", url))
        with self.assertRaises(APIError):
            change_service("stop", self.request, SimpleNamespace(id=uuid4()), service["generation"])
        change_service("stop", self.request, self.user, service["generation"])
        self.assertIsNone(self.check()["base_url"])
        self.tcloud.cli.assert_called_with("cancel", "-j", "8123")
        self.tcloud.queued.return_value = False
        self.assertEqual(self.check()["state"], "stopped")

    def test_disk_full_and_lost_ack(self):
        change_service("start", self.request, self.user)
        self.tcloud.cli.return_value = (1, "No space left on device\n[Tcloud Error] sdk tcloudcli.go:317: Failed to upload env repository")
        self.assertIn("空间不足", self.check()["detail"])
        change_service("start", self.request, self.user)
        self.tcloud.cli.side_effect = [(1, "connection closed"), (1, "missing"), (0, "8123")]
        self.assertEqual(self.check()["state"], "unconfirmed")
        self.assertEqual(self.check()["job_id"], "8123")

    def test_url_override_is_account_scoped_and_does_not_start_or_stop_jobs(self):
        other = SimpleNamespace(id=uuid4())
        url = "http://10.0.3.10:8000/v1"
        save_shared(SharedEndpointInput(base_url=url + "/"), self.request, self.user)
        self.assertEqual(models(self.request, self.user)["shared_url"], url)
        self.assertIsNone(models(self.request, other)["shared_url"])
        self.assertEqual(self.check()["state"], "stopped")
        remove_shared(self.request, self.user)
        self.assertIsNone(models(self.request, self.user)["shared_url"])
        self.tcloud.cli.assert_not_called()
        with self.assertRaises(ValueError):
            SharedEndpointInput(base_url="https://example.org/v1")
