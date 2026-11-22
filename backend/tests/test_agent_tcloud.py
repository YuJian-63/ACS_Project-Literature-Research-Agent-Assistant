import json
import time
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import test_agent_bridge as bridge_tests
from app.agent_bridge.bundles import export_bundle, manifest_digest
from app.agent_bridge.tcloud import TcloudTransport, stage_model_env
from app.agent_bridge.transport import TransportError, create_transport, transport_name


class TcloudTests(unittest.TestCase):
    def setUp(self):
        self.fixture = bridge_tests.AgentBridgeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manifest = self.fixture.manifest
        self.settings = self.fixture.settings.model_copy(update={
            "agent_transport": "tcloud", "agent_library_public_url": "https://library.example",
        })
        self.transport = create_transport(self.settings)
        self.assertIsInstance(self.transport, TcloudTransport)
        self.assertEqual(transport_name(self.settings), "tcloud-v1")
        self.deadline = time.time() + 180
        self.bundle = export_bundle(self.manifest, self.fixture.root, self.settings.resolved_agent_exchange_root,
            include_pdfs=False)
        self.bundle.with_name("library-access.json").write_text('{"base_url":"https://library.example","token":"fixture"}')
        self.status = {"schema_version": "agent-job-status-v1", "dispatch_id": str(self.manifest.dispatch_id),
            "input_sha256": manifest_digest(self.manifest), "remote_job_id": "8123", "state": "running",
            "updated_at": datetime.now(timezone.utc).isoformat()}

    def test_submit_stages_only_job_inputs_and_recovers_the_receipt_on_restart(self):
        def submit(*args, cwd, timeout):
            self.assertEqual(args, ("submit",))
            self.assertGreater(timeout, self.settings.agent_transport_timeout_seconds)
            self.assertLessEqual(timeout, self.settings.agent_tcloud_submit_timeout_seconds)
            self.assertEqual(cwd.name, f"acs-{self.manifest.dispatch_id}")
            self.assertTrue((cwd / "agent" / "baseline.py").is_file())
            self.assertTrue((cwd / "run_job.py").is_file())
            self.assertEqual(json.loads((cwd / "dispatch.json").read_text())["input_sha256"], manifest_digest(self.manifest))
            self.assertFalse(any(p.name == ".env" or p.name == ".git" for p in cwd.rglob("*")))
            with zipfile.ZipFile(cwd / "input.zip") as bundle:
                self.assertEqual(set(bundle.namelist()), {"task.json", "sources.json", "manifest.json"})
                self.assertEqual(json.loads(bundle.read("sources.json"))[0]["paper_id"], str(self.fixture.paper_id))
            return 0, "Submitted batch job 8123\r\n"

        with patch.object(self.transport, "cli", side_effect=submit):
            self.assertEqual(self.transport.submit(self.manifest, deadline=self.deadline), "8123")
        restarted = TcloudTransport(self.settings)
        with patch.object(restarted, "cli", side_effect=AssertionError("Duplicate submission")):
            self.assertEqual(restarted.submit(self.manifest, deadline=self.deadline), "8123")
            with self.assertRaises(ValueError):
                restarted.submit(self.manifest, "9000", deadline=self.deadline)
        self.assertFalse(list(restarted.jobs(self.manifest).rglob("model.env")))

    def test_course_task_stages_only_its_live_service(self):
        from app.agent_bridge.contracts import ResearchOptions
        generation = uuid4()
        self.manifest.runtime.research = ResearchOptions(model_provider="tacc")
        self.manifest.runtime.service_generation = generation
        service = Mock(state="ready", stop_requested=False, generation=generation, base_url="http://10.0.0.8:8000/v1")
        from unittest.mock import MagicMock
        self.transport.sessions = MagicMock()
        self.transport.sessions.return_value.__enter__.return_value.get.return_value = service
        target = self.fixture.root / "course-stage"
        self.transport.stage(self.manifest, target, self.deadline)
        config = (target / "model.env").read_text()
        self.assertIn("MODEL_BASE_URL=http://10.0.0.8:8000/v1", config)
        self.assertIn("MODEL_PROVIDER=tacc", config)
        self.assertNotIn("BAILIAN_API_KEY", config)
        service.generation = uuid4()
        with self.assertRaisesRegex(TransportError, "COURSE_MODEL_UNAVAILABLE"):
            self.transport.stage(self.manifest, self.fixture.root / "stale-stage", self.deadline)

        self.manifest.runtime.research = ResearchOptions(model_provider="custom", endpoint_url="http://10.0.3.10:8000/v1")
        manual = self.fixture.root / "url-stage"
        self.transport.stage(self.manifest, manual, self.deadline)
        self.assertIn("MODEL_BASE_URL=http://10.0.3.10:8000/v1", (manual / "model.env").read_text())

    def test_only_proven_pre_submit_failure_can_retry(self):
        failed = (255, "[Tcloud Error] 2026/11/21 tcloudcli.go:322: Failed to upload env repository\n")
        with patch.object(self.transport, "cli", return_value=failed) as command:
            with self.assertRaises(TransportError) as failure:
                self.transport.submit(self.manifest, deadline=self.deadline)
            self.assertTrue(failure.exception.retryable)
            self.assertEqual(failure.exception.code, "AGENT_TCLOUD_UPLOAD_FAILED")
            self.assertEqual(self.transport.receipt(self.manifest)["outcome"], "not_submitted")
            command.return_value = (0, "Submitted batch job 8123\r\n")
            self.assertEqual(self.transport.submit(self.manifest, deadline=self.deadline), "8123")
            self.assertEqual(command.call_count, 2)

    def test_timeout_preserves_ambiguity_and_any_scheduler_ack_already_received(self):
        import subprocess
        sdk = "Env acs-network-probe exists, dependencies updated.\n"
        error = subprocess.TimeoutExpired("tcloud", 180, output=sdk.encode())
        with patch("app.agent_bridge.tcloud.subprocess.run", side_effect=error):
            with self.assertRaises(TransportError) as uncertain:
                self.transport.submit(self.manifest, deadline=self.deadline)
        self.assertEqual(uncertain.exception.code, "AGENT_SUBMISSION_UNCERTAIN")
        receipt = self.transport.receipt(self.manifest)
        self.assertEqual((receipt["outcome"], receipt["phase"], receipt["error"]), ("uncertain", "scheduler", "timeout"))
        with patch.object(self.transport, "remote_status", return_value=None), patch.object(self.transport, "cli") as command:
            with self.assertRaises(TransportError):
                self.transport.submit(self.manifest, deadline=self.deadline)
            command.assert_not_called()
        # A platform may acknowledge the job before the SSH command itself hangs.
        error.stdout = (sdk + "Submitted batch job 8123\n").encode()
        another = self.manifest.model_copy(update={"dispatch_id": uuid4()})
        with patch.object(self.transport, "stage"), patch("app.agent_bridge.tcloud.subprocess.run", side_effect=error):
            self.assertEqual(self.transport.submit(another, deadline=self.deadline), "8123")

    def test_lost_reply_waits_for_the_bound_status_and_never_resubmits(self):
        with patch.object(self.transport, "cli", return_value=(0, "Disconnected")):
            with self.assertRaises(TransportError) as uncertain:
                self.transport.submit(self.manifest, deadline=self.deadline)
            self.assertTrue(uncertain.exception.retryable)
        restarted = TcloudTransport(self.settings)
        def download(command, remote, local):
            self.assertEqual(command, "download")
            self.assertEqual(remote, f"acs-research/jobs/{self.manifest.dispatch_id}/status.json")
            Path(local).write_text(json.dumps(self.status))
            return 0, ""
        with patch.object(restarted, "cli", return_value=(0, "[Tcloud Error] scp: No such file or directory")):
            with self.assertRaises(TransportError):
                restarted.submit(self.manifest, deadline=self.deadline)
        with patch.object(restarted, "cli", side_effect=download):
            self.assertEqual(restarted.submit(self.manifest, deadline=self.deadline), "8123")

    def test_fetch_after_job_leaves_queue_and_reject_mismatched_result(self):
        self.transport.jobs(self.manifest).mkdir(parents=True)
        delivery = self.fixture.delivery() | {"remote_job_id": "9999"}
        def cli(command, *args):
            if command == "ps":
                return 0, "slurm_load_jobs error: Invalid job id specified\r\n[Tcloud Error]"
            self.assertEqual(command, "download")
            remote, local = args
            content = (self.status | {"state": "succeeded", "stop_reason": "completed"}
                       if remote.endswith("/status.json") else delivery)
            Path(local).write_text(json.dumps(content))
            return 0, ""
        with patch.object(self.transport, "cli", side_effect=cli):
            with self.assertRaises(ValueError):
                self.transport.poll(self.manifest, "8123")
            self.assertIsNone(self.transport.download(self.manifest, "8123"))
            delivery["remote_job_id"] = "8123"
            self.assertEqual(self.transport.poll(self.manifest, "8123").state, "succeeded")
            path = self.transport.download(self.manifest, "8123")
            self.assertEqual(json.loads(path.read_text()), delivery)

    def test_cancel_confirms_queue_disappearance_before_acknowledging(self):
        calls = []
        def cli(*args):
            calls.append(args)
            if args[0] == "cancel":
                return 0, ""
            return 0, "JOBID PARTITION\n8123 tacc\n" if len(calls) == 1 else "JOBID PARTITION\n"
        with patch.object(self.transport, "cli", side_effect=cli):
            self.assertFalse(self.transport.cancel(self.manifest, "8123"))
            self.assertTrue(self.transport.cancel(self.manifest, "8123"))
            self.assertEqual(calls.count(("cancel", "-j", "8123")), 1)
            with self.assertRaises(TransportError):
                self.transport.submit(self.manifest, deadline=self.deadline)

    def test_only_a_short_lived_official_model_token_is_staged(self):
        source, target = self.fixture.root / "private.env", self.fixture.root / "model.env"
        key = "local-signing-fixture"
        endpoint = "https://workspace.cn-beijing.maas.aliyuncs.com"
        config = f"MODEL_BASE_URL={endpoint}/compatible-mode/v1\nBAILIAN_API_KEY={key}\nTAVILY_API_KEY=unrelated\n"
        source.write_text(config)
        source.chmod(0o600)
        response = Mock(status_code=200)
        response.json.return_value = {"token": "st-temporary", "expires_at": int(self.deadline)}
        with patch("app.agent_bridge.tcloud.httpx.post", return_value=response) as issue:
            stage_model_env(source, target, self.deadline)
            args, kwargs = issue.call_args
            self.assertEqual(args, (endpoint + "/api/v1/tokens",))
            self.assertEqual(kwargs["headers"], {"Authorization": "Bearer " + key})
            self.assertFalse(kwargs["follow_redirects"])
            self.assertFalse(kwargs["trust_env"])
            self.assertLessEqual(kwargs["params"]["expire_in_seconds"], 180)
            self.assertEqual(target.stat().st_mode & 0o077, 0)
            self.assertIn("BAILIAN_API_KEY=st-temporary", target.read_text())
            for forbidden in (key, "TAVILY", "unrelated"):
                self.assertNotIn(forbidden, target.read_text())
            for token, expiry in ((key, self.deadline), ("st-expired", time.time() - 30), ("st-too-long", self.deadline + 60)):
                response.json.return_value = {"token": token, "expires_at": int(expiry)}
                with self.assertRaises(TransportError):
                    stage_model_env(source, target, self.deadline)
            source.write_text(config.replace(endpoint, "https://dashscope.aliyuncs.com.attacker.example"))
            issue.reset_mock()
            with self.assertRaises(ValueError):
                stage_model_env(source, target, self.deadline)
            issue.assert_not_called()
