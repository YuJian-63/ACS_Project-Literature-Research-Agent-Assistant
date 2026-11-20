import tarfile
import tempfile
import unittest
from pathlib import Path

from app.agent_bridge.deploy import build_runtime_archive


class AgentDeployTests(unittest.TestCase):
    def test_deploy_archive_is_an_explicit_code_allowlist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = Path(__file__).resolve().parents[2] / "agent"
            target = build_runtime_archive(source, root / "agent.tar.gz")
            with tarfile.open(target) as archive:
                names = archive.getnames()
            self.assertIn("run_dispatch.py", names)
            self.assertIn("tacc_bridge.py", names)
            self.assertIn("pyproject.toml", names)
            self.assertIn("uv.lock", names)
            self.assertTrue(any(name.startswith("agent_io/") for name in names))
            self.assertFalse(
                any(
                    name.startswith(("tests/", ".venv/", "data/", "runs/"))
                    for name in names
                )
            )
            self.assertFalse(
                any(
                    name.endswith((".key", ".pem", ".pyc"))
                    or Path(name).name in {".env", "tacc.local.json", "api-keys.txt"}
                    for name in names
                )
            )
