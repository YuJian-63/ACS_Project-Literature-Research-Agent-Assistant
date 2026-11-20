import json
import unittest
from unittest.mock import patch

import test_agent_bridge as bridge_tests
from app.agent_bridge.bundles import canonical_json, manifest_digest
from app.agent_bridge.tacc import TaccTransport
from app.agent_bridge.transport import TransportError


class TaccTransportTests(unittest.TestCase):
    def test_task_response_exposes_each_supported_transport(self):
        from app.api.schemas import AgentExecution

        for transport in ("file-exchange-v1", "local-process-v1", "tacc-ssh-slurm-v1"):
            value = AgentExecution(
                dispatch_id="00000000-0000-4000-8000-000000000001",
                transport=transport,
                limits={},
            )
            self.assertEqual(value.transport, transport)

    def setUp(self):
        fixture = bridge_tests.AgentBridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.manifest = fixture.manifest
        self.settings = fixture.settings.model_copy(
            update={
                "agent_transport": "tacc",
                "agent_tacc_host": "research-cluster",
                "agent_tacc_helper": "/home/research/agent/tacc_bridge.py",
                "agent_tacc_config": "/home/research/agent/tacc.json",
            }
        )
        self.transport = TaccTransport(self.settings)

    def test_ssh_uses_host_verification_batch_mode_and_no_local_shell(self):
        def reply(arguments, **kwargs):
            self.assertIn("StrictHostKeyChecking=yes", arguments)
            self.assertIn("BatchMode=yes", arguments)
            self.assertFalse(kwargs.get("shell", False))
            request = json.loads(kwargs["stdin"].readline())
            self.assertEqual(request["op"], "submit")
            kwargs["stdout"].write(
                canonical_json(
                    {
                        "schema_version": "agent-transport-v1",
                        "ok": True,
                        "dispatch_id": str(self.manifest.dispatch_id),
                        "input_sha256": manifest_digest(self.manifest),
                        "data": {"job_id": "8123"},
                    }
                )
            )

        with patch("app.agent_bridge.tacc.subprocess.run", side_effect=reply):
            self.assertEqual(self.transport.submit(self.manifest), "8123")

    def test_terminal_scheduler_failure_and_missing_result_are_explicit(self):
        for state, code in (
            ("FAILED", "AGENT_PLATFORM_FAILED"),
            ("TIMEOUT", "AGENT_PLATFORM_TIMEOUT"),
            ("COMPLETED", "AGENT_RESULT_MISSING"),
        ):
            with (
                self.subTest(state=state),
                patch.object(
                    self.transport,
                    "_rpc",
                    return_value={
                        "job_id": "8123",
                        "platform_state": state,
                        "status": None,
                        "has_result": False,
                    },
                ),
            ):
                with self.assertRaises(TransportError) as raised:
                    self.transport.poll(self.manifest, "8123")
                self.assertEqual(raised.exception.code, code)

    def test_saved_job_id_cannot_change(self):
        with patch.object(self.transport, "_rpc", return_value={"job_id": "9999"}):
            with self.assertRaises(ValueError):
                self.transport.submit(self.manifest, "8123")
