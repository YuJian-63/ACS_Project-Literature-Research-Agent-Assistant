import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import test_agent_bridge as bridge_tests
from app.agent_bridge.bundles import canonical_json, export_bundle, manifest_digest
from app.agent_bridge.status import read_status
from app.agent_bridge.transport import LocalTransport, TransportError, create_transport


class AgentTransportTests(unittest.TestCase):
    def setUp(self):
        fixture = bridge_tests.AgentBridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.manifest = fixture.manifest
        self.root = fixture.root
        self.agent_root = self.root / "standalone agent"
        self.agent_root.mkdir()
        (self.agent_root / "run_dispatch.py").write_text(
            "raise SystemExit(0)", encoding="utf-8"
        )
        self.settings = fixture.settings.model_copy(
            update={
                "agent_transport": "local",
                "agent_local_root": self.agent_root,
                "agent_local_python": Path(sys.executable),
            }
        )
        self.transport = LocalTransport(self.settings)
        self.bundle = export_bundle(
            self.manifest, self.root, self.settings.resolved_agent_exchange_root
        )
        self.job_id = f"local:{self.manifest.dispatch_id}"
        self.directory = (
            self.settings.resolved_agent_exchange_root
            / "jobs"
            / str(self.manifest.dispatch_id)
        )

    def status(self, state="running", reason=None, error=None):
        return {
            "schema_version": "agent-job-status-v1",
            "dispatch_id": str(self.manifest.dispatch_id),
            "input_sha256": manifest_digest(self.manifest),
            "remote_job_id": self.job_id,
            "state": state,
            "stop_reason": reason,
            "error": error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def submit(self):
        self.transport.upload(self.manifest, self.bundle)
        with patch("app.agent_bridge.transport.subprocess.Popen") as spawn:
            self.assertEqual(self.transport.submit(self.manifest), self.job_id)
        return spawn

    def test_manual_is_default_and_local_requires_an_explicit_environment(self):
        self.assertEqual(
            type(create_transport(self.fixture.settings)).__name__, "ManualTransport"
        )
        with self.assertRaises(ValueError):
            create_transport(
                self.fixture.settings.model_copy(update={"agent_transport": "local"})
            )

    def test_status_checks_identity_state_consistency_duplicates_and_size(self):
        path = self.root / "status.json"
        path.write_bytes(canonical_json(self.status()))
        self.assertEqual(read_status(path, self.manifest, self.job_id).state, "running")
        for changes in (
            {"dispatch_id": str(uuid4())},
            {"input_sha256": "0" * 64},
            {"remote_job_id": "foreign"},
            {"state": "queued"},
            {"state": "succeeded", "stop_reason": "model_error"},
            {"state": "running", "error": {"code": "FAIL", "type": "ValueError"}},
        ):
            with self.subTest(changes=changes):
                path.write_bytes(canonical_json(self.status() | changes))
                with self.assertRaises(ValueError):
                    read_status(path, self.manifest, self.job_id)
        path.write_text('{"state":"running","state":"failed"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            read_status(path, self.manifest, self.job_id)
        path.write_bytes(b" " * 65537)
        with self.assertRaises(ValueError):
            read_status(path, self.manifest, self.job_id)

    def test_upload_and_submit_are_durable_and_launch_only_once(self):
        spawn = self.submit()
        self.assertEqual(spawn.call_count, 1)
        self.assertFalse(spawn.call_args.kwargs.get("shell", False))
        self.assertTrue((self.directory / "input.zip").is_file())
        self.assertEqual(
            (self.directory / "input.zip").read_bytes(), self.bundle.read_bytes()
        )
        restored = LocalTransport(self.settings)
        restored.upload(self.manifest, self.bundle)
        with patch("app.agent_bridge.transport.subprocess.Popen") as again:
            self.assertEqual(restored.submit(self.manifest, self.job_id), self.job_id)
        again.assert_not_called()
        record = json.loads((self.directory / "submission.json").read_bytes())
        self.assertEqual(record["input_sha256"], manifest_digest(self.manifest))
        self.assertNotIn("API_KEY", json.dumps(record))

    def test_missing_record_with_saved_job_never_resubmits(self):
        self.transport.upload(self.manifest, self.bundle)
        with patch("app.agent_bridge.transport.subprocess.Popen") as spawn:
            with self.assertRaises(TransportError) as raised:
                self.transport.submit(self.manifest, self.job_id)
        self.assertEqual(raised.exception.code, "AGENT_SUBMISSION_UNCERTAIN")
        spawn.assert_not_called()

    def test_submission_persists_original_task_deadline(self):
        self.transport.upload(self.manifest, self.bundle)
        deadline = time.time() + 25
        with patch("app.agent_bridge.transport.subprocess.Popen"):
            self.transport.submit(self.manifest, deadline=deadline)
        record = json.loads((self.directory / "submission.json").read_bytes())
        self.assertEqual(record["deadline"], deadline)
        with patch("app.agent_bridge.transport.subprocess.Popen") as spawn:
            self.transport.submit(self.manifest, deadline=deadline + 500)
        spawn.assert_not_called()
        self.assertEqual(
            json.loads((self.directory / "submission.json").read_bytes())["deadline"],
            deadline,
        )

    def test_expired_supervisor_never_launches_agent(self):
        from app.agent_bridge.local_job import supervise

        self.submit()
        target = self.directory / "submission.json"
        record = json.loads(target.read_bytes())
        record["deadline"] = time.time() - 1
        target.write_bytes(canonical_json(record))
        with patch("app.agent_bridge.local_job.subprocess.Popen") as spawn:
            self.assertEqual(supervise(target), 1)
        spawn.assert_not_called()
        self.assertEqual(
            json.loads((self.directory / "exit.json").read_bytes())["error"],
            "AGENT_PROCESS_TIMEOUT",
        )

    def test_launch_error_is_recorded_and_not_retried(self):
        self.transport.upload(self.manifest, self.bundle)
        with patch(
            "app.agent_bridge.transport.subprocess.Popen",
            side_effect=OSError("private path"),
        ):
            with self.assertRaises(TransportError) as raised:
                self.transport.submit(self.manifest)
        self.assertEqual(raised.exception.code, "AGENT_LAUNCH_FAILED")
        with patch("app.agent_bridge.transport.subprocess.Popen") as spawn:
            self.assertEqual(
                LocalTransport(self.settings).submit(self.manifest), self.job_id
            )
            with self.assertRaises(TransportError) as raised:
                self.transport.poll(self.manifest, self.job_id)
        self.assertEqual(raised.exception.code, "AGENT_LAUNCH_FAILED")
        spawn.assert_not_called()
        self.assertNotIn("private path", (self.directory / "exit.json").read_text())

    def test_process_exit_without_artifacts_fails_instead_of_waiting(self):
        self.submit()
        receipt = {
            "schema_version": "agent-local-exit-v1",
            "dispatch_id": str(self.manifest.dispatch_id),
            "input_sha256": manifest_digest(self.manifest),
            "remote_job_id": self.job_id,
            "returncode": 2,
            "error": None,
        }
        (self.directory / "exit.json").write_bytes(canonical_json(receipt))
        with self.assertRaises(TransportError) as raised:
            self.transport.poll(self.manifest, self.job_id)
        self.assertEqual(raised.exception.code, "AGENT_PROCESS_FAILED")

    def test_crash_after_running_status_does_not_wait_until_task_timeout(self):
        self.submit()
        (self.directory / "status.json").write_bytes(canonical_json(self.status()))
        (self.directory / "exit.json").write_bytes(
            canonical_json(
                {
                    "schema_version": "agent-local-exit-v1",
                    "dispatch_id": str(self.manifest.dispatch_id),
                    "input_sha256": manifest_digest(self.manifest),
                    "remote_job_id": self.job_id,
                    "returncode": 2,
                    "error": None,
                }
            )
        )
        with self.assertRaises(TransportError) as raised:
            self.transport.poll(self.manifest, self.job_id)
        self.assertEqual(raised.exception.code, "AGENT_PROCESS_FAILED")

    def test_result_is_validated_before_atomic_download(self):
        self.submit()
        delivery = self.fixture.delivery()
        delivery["remote_job_id"] = self.job_id
        (self.directory / "result.json").write_bytes(canonical_json(delivery))
        incoming = self.transport.download(self.manifest, self.job_id)
        self.assertEqual(json.loads(incoming.read_bytes()), delivery)
        self.assertFalse(list(incoming.parent.glob("*.part")))
        delivery["input_sha256"] = "f" * 64
        (self.directory / "result.json").write_bytes(canonical_json(delivery))
        with self.assertRaises(ValueError):
            self.transport.download(self.manifest, self.job_id)
        self.assertNotEqual(json.loads(incoming.read_bytes())["input_sha256"], "f" * 64)

    def test_upload_rejects_changed_existing_input(self):
        self.transport.upload(self.manifest, self.bundle)
        (self.directory / "input.zip").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.transport.upload(self.manifest, self.bundle)

    def test_cancellation_before_submission_permanently_fences_launch(self):
        self.transport.upload(self.manifest, self.bundle)
        self.assertTrue(self.transport.cancel(self.manifest, None))
        with patch("app.agent_bridge.transport.subprocess.Popen") as spawn:
            with self.assertRaises(TransportError):
                self.transport.submit(self.manifest)
        spawn.assert_not_called()

    def test_unsubmitted_cancelled_job_can_be_cleaned_after_retention(self):
        self.transport.upload(self.manifest, self.bundle)
        self.assertTrue(self.transport.cancel(self.manifest, None))
        marker = self.directory / "cancel.request"
        os.utime(
            marker, (time.time() - self.settings.agent_retention_seconds - 10,) * 2
        )
        self.assertTrue(self.transport.cleanup(self.manifest, None, apply=True))
        self.assertFalse(self.directory.exists())

    def test_partial_cleanup_reentry_does_not_depend_on_an_internal_marker(self):
        self.submit()
        receipt = self.directory / "exit.json"
        receipt.write_bytes(
            canonical_json(
                {
                    "schema_version": "agent-local-exit-v1",
                    "dispatch_id": str(self.manifest.dispatch_id),
                    "input_sha256": manifest_digest(self.manifest),
                    "remote_job_id": self.job_id,
                    "returncode": 2,
                    "error": None,
                }
            )
        )
        os.utime(
            receipt, (time.time() - self.settings.agent_retention_seconds - 10,) * 2
        )

        def interrupted(directory):
            (directory / "retired.json").unlink(missing_ok=True)
            raise OSError("interrupted cleanup")

        with patch(
            "app.agent_bridge.maintenance.shutil.rmtree", side_effect=interrupted
        ):
            with self.assertRaises(OSError):
                self.transport.cleanup(self.manifest, self.job_id, apply=True)
        self.assertTrue(self.transport.cleanup(self.manifest, self.job_id, apply=True))
        self.assertFalse(self.directory.exists())

    def test_cleaned_local_dispatch_cannot_be_submitted_again(self):
        self.submit()
        receipt = self.directory / "exit.json"
        receipt.write_bytes(
            canonical_json(
                {
                    "schema_version": "agent-local-exit-v1",
                    "dispatch_id": str(self.manifest.dispatch_id),
                    "input_sha256": manifest_digest(self.manifest),
                    "remote_job_id": self.job_id,
                    "returncode": 2,
                    "error": None,
                }
            )
        )
        os.utime(
            receipt, (time.time() - self.settings.agent_retention_seconds - 10,) * 2
        )
        self.assertTrue(self.transport.cleanup(self.manifest, self.job_id))
        self.assertTrue(self.directory.exists())
        self.assertTrue(self.transport.cleanup(self.manifest, self.job_id, apply=True))
        self.assertTrue(self.transport.cleanup(self.manifest, self.job_id, apply=True))
        with patch("app.agent_bridge.transport.subprocess.Popen") as spawn:
            with self.assertRaises(TransportError) as raised:
                self.transport.submit(self.manifest, self.job_id)
        self.assertEqual(raised.exception.code, "AGENT_DISPATCH_RETIRED")
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
