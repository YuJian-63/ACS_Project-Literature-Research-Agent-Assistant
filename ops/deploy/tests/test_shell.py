import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("ACS_BASH") or shutil.which("bash")


@unittest.skipUnless(BASH, "Bash is required for deployment script checks")
class DeploymentShellTests(unittest.TestCase):
    def test_frontend_verification_handles_http_to_https_redirects(self):
        source = (ROOT / "deploy-ecs.sh").read_text(encoding="utf-8")
        publish = '\nas_acs mv -f "$site/.index-$run_id.html" "$site/index.html"\n'
        verification = source.split(publish, 1)[1].split('\ncurl --noproxy', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            backup = root / "backup"
            (release / "frontend").mkdir(parents=True)
            backup.mkdir()
            (release / "frontend/index.html").write_text("<!doctype html>\n", encoding="utf-8")
            script = "\n".join((
                "set -euo pipefail",
                "release=" + shlex.quote(release.as_posix()),
                "backup=" + shlex.quote(backup.as_posix()),
                'curl() {',
                '    printf "%s\\n" "$@" > "$backup/curl-arguments.txt"',
                '    if [[ " $* " == *" https://8.218.149.237/ "* ]]; then',
                '        cat "$release/frontend/index.html"',
                '    else',
                '        printf "<html>308 Permanent Redirect</html>\\n"',
                '    fi',
                '}',
                verification,
            ))
            result = subprocess.run([BASH, "-c", script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            arguments = (backup / "curl-arguments.txt").read_text(encoding="utf-8").splitlines()
            self.assertIn("https://8.218.149.237/", arguments)
            resolve = arguments.index("--resolve")
            self.assertEqual(arguments[resolve + 1], "8.218.149.237:443:127.0.0.1")

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

    def test_running_evaluation_worker_participates_in_deployment_lifecycle(self):
        source = (ROOT / "deploy-ecs.sh").read_text(encoding="utf-8")
        setup = "services=(" + source.split("services=(", 1)[1].split("\nas_acs() {", 1)[0]
        for active in (0, 1):
            with self.subTest(active=active):
                script = "\n".join((
                    f"evaluation_active={active}",
                    'systemctl() { [[ "$*" == "is-active --quiet acs-evaluation.service" && "$evaluation_active" == 1 ]]; }',
                    setup,
                    "include_running_evaluation",
                    'printf "service:%s\\n" "${services[@]}"',
                    'printf "worker:%s\\n" "${workers[@]}"',
                ))
                result = subprocess.run([BASH, "-c", script], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                for prefix in ("service:", "worker:"):
                    self.assertEqual(prefix + "acs-evaluation.service" in result.stdout.splitlines(), bool(active))

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
