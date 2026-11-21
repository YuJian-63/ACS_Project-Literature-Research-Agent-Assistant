import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("ACS_BASH") or shutil.which("bash")


@unittest.skipUnless(BASH, "Bash is required for deployment script checks")
class DeploymentShellTests(unittest.TestCase):
    def test_failure_after_switch_stops_all_application_services(self):
        source = (ROOT / "deploy-ecs.sh").read_text(encoding="utf-8")
        body = source.split("failure() {", 1)[1].split("\n}\n", 1)[0]
        script = "\n".join((
            "maintenance=1; code_switched=1; migration=completed; backup=test",
            "services=(acs-api.service acs-runner.service)",
            "systemctl() { printf 'systemctl %s\\n' \"$*\"; }",
            "failure() {" + body + "\n}",
            "failure 17",
        ))
        result = subprocess.run([BASH, "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertIn("systemctl stop acs-api.service acs-runner.service", result.stdout)

    def test_server_scripts_have_valid_syntax(self):
        for name in ("setup-ecs.sh", "deploy-ecs.sh"):
            with self.subTest(name=name):
                result = subprocess.run([BASH, "-n", str(ROOT / name)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_deployment_rejects_invalid_arguments_before_operations(self):
        for arguments in ([], ["a" * 40], ["../../outside", "123-1"], ["a" * 40, "../bad"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [BASH, str(ROOT / "deploy-ecs.sh"), *arguments],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Usage: acs-deploy-release", result.stderr)


if __name__ == "__main__":
    unittest.main()
