import json
import os
import unittest
from zipfile import ZipFile
from pydantic import SecretStr
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import test_agent_bridge as bridge_tests
from app.agent_bridge.contracts import ResultEnvelope
from app.agent_bridge.status import JobStatus
from app.agent_bridge.transport import TransportError
from app.agent_bridge.worker import AgentWorker


class AgentWorkerTests(unittest.TestCase):
    def setUp(self):
        fixture = bridge_tests.AgentBridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.manifest = fixture.manifest
        self.task_id = UUID(self.manifest.task.task_id)
        self.transport = Mock()
        self.transport.submit.return_value = "remote-job-fixture"
        self.transport.poll.return_value = None
        self.transport.download.return_value = None
        self.worker = AgentWorker(Mock(), fixture.settings, transport=self.transport)
        self.execution = SimpleNamespace(
            manifest=self.manifest,
            job_id=None,
            transport="file-exchange-v1",
            deadline=1900000000.0,
        )
        for name, value in (
            ("load_execution", self.execution),
            ("set_task_stage", True),
            ("record_job", True),
            ("complete_delivery", True),
            ("fail_owned", True),
            ("cancel_terminal", None),
            ("heartbeat", True),
        ):
            patcher = patch("app.agent_bridge.worker." + name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def status(self, state, reason=None, error=None):
        from datetime import datetime, timezone

        from app.agent_bridge.bundles import manifest_digest

        return JobStatus(
            schema_version="agent-job-status-v1",
            dispatch_id=self.manifest.dispatch_id,
            input_sha256=manifest_digest(self.manifest),
            remote_job_id="remote-job-fixture",
            state=state,
            stop_reason=reason,
            error=error,
            updated_at=datetime.now(timezone.utc),
        )

    def test_full_research_failure_is_saved_instead_of_replaced_by_wrapper_error(self):
        path = self.fixture.root / "result.json"
        envelope = ResultEnvelope.model_validate(self.fixture.delivery("model_error"))
        path.write_text(envelope.model_dump_json(), encoding="utf-8")
        self.transport.poll.return_value = self.status("failed", "model_error")
        self.transport.download.return_value = path
        self.worker.execute(self.task_id)
        self.complete_delivery.assert_called_once()
        self.fail_owned.assert_not_called()
        self.record_job.assert_called_once()

    def test_wrapper_failure_without_result_fails_promptly_with_safe_details(self):
        self.transport.poll.return_value = self.status(
            "failed", error={"code": "EXECUTION_ERROR", "type": "ValueError"}
        )
        self.worker.execute(self.task_id)
        self.assertEqual(self.fail_owned.call_args.args[3], "AGENT_WRAPPER_FAILED")
        self.assertEqual(
            self.fail_owned.call_args.kwargs["details"]["wrapper_code"],
            "EXECUTION_ERROR",
        )

    def test_online_job_receives_private_credentials_separately_from_its_input(self):
        from app.auth.agent_library import issue_job_library_token

        url = "https://library.example.org"
        settings = self.worker.settings.model_copy(update={
            "agent_library_public_url": url, "auth_csrf_key": SecretStr("fixture-key" * 4),
        })
        self.worker.settings = settings
        self.transport.poll.return_value = self.status("failed", "model_error")
        self.worker.execute(self.task_id)
        _, bundle = self.transport.upload.call_args.args
        private = bundle.with_name("library-access.json")
        token = issue_job_library_token(settings, self.manifest.dispatch_id, self.execution.deadline)
        self.assertEqual(json.loads(private.read_text()), {"base_url": url, "token": token})
        if os.name == "posix":
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        with ZipFile(bundle) as archive:
            self.assertNotIn(private.name, archive.namelist())
            self.assertNotIn(token.encode(), archive.read("manifest.json"))
        self.complete_delivery.assert_not_called()

    def test_success_status_without_result_never_marks_task_success(self):
        self.transport.poll.return_value = self.status("succeeded", "completed")
        self.worker.execute(self.task_id)
        self.assertEqual(self.fail_owned.call_args.args[3], "AGENT_RESULT_MISSING")
        self.complete_delivery.assert_not_called()

    def test_transient_transport_failure_retries_same_dispatch_and_saved_job(self):
        self.execution.job_id = "remote-job-fixture"
        self.transport.upload.side_effect = [
            TransportError("AGENT_TRANSPORT_UNAVAILABLE", retryable=True),
            None,
        ]
        self.transport.poll.return_value = self.status(
            "failed", error={"code": "EXECUTION_ERROR", "type": "ValueError"}
        )
        with patch.object(self.worker.stopped, "wait", return_value=False):
            self.worker.execute(self.task_id)
        self.assertEqual(self.transport.upload.call_count, 2)
        self.transport.submit.assert_called_once_with(
            self.manifest, "remote-job-fixture", deadline=self.execution.deadline
        )

    def test_lost_lease_does_not_submit_or_save(self):
        self.set_task_stage.return_value = False
        self.worker.execute(self.task_id)
        self.transport.submit.assert_not_called()
        self.complete_delivery.assert_not_called()

    def test_lease_is_checked_again_after_upload(self):
        self.heartbeat.return_value = False
        self.worker.execute(self.task_id)
        self.transport.upload.assert_called_once()
        self.transport.submit.assert_not_called()

    def test_result_and_status_stop_reasons_must_agree(self):
        path = self.fixture.root / "result.json"
        path.write_text(
            ResultEnvelope.model_validate(self.fixture.delivery()).model_dump_json(),
            encoding="utf-8",
        )
        self.transport.poll.return_value = self.status("failed", "model_error")
        self.transport.download.return_value = path
        self.worker.execute(self.task_id)
        self.assertEqual(self.fail_owned.call_args.args[3], "AGENT_DELIVERY_INVALID")
        self.complete_delivery.assert_not_called()

    def test_manual_status_and_result_job_ids_must_agree(self):
        self.transport.submit.return_value = None
        path = self.fixture.root / "result.json"
        path.write_text(
            ResultEnvelope.model_validate(self.fixture.delivery()).model_dump_json(),
            encoding="utf-8",
        )
        self.transport.poll.return_value = self.status(
            "succeeded", "completed"
        ).model_copy(update={"remote_job_id": "other-job"})
        self.transport.download.return_value = path
        self.worker.execute(self.task_id)
        self.assertEqual(self.fail_owned.call_args.args[3], "AGENT_DELIVERY_INVALID")
        self.complete_delivery.assert_not_called()
