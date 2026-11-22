import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BASH = os.environ.get("ACS_BASH") or shutil.which("bash")
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="service scripts ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "scripts").mkdir()
        self.arguments = self.root / "arguments.json"

    @unittest.skipUnless(POWERSHELL, "PowerShell is not installed")
    def test_windows_preserves_paths_arguments_and_exit_code(self):
        script = self.root / "scripts/service-windows.ps1"
        shutil.copyfile(ROOT / "scripts/service-windows.ps1", script)
        command = r'''
function uv {
    [IO.File]::WriteAllText($env:TEST_ARGUMENT_FILE, (ConvertTo-Json -Compress -InputObject @($args)))
    $global:LASTEXITCODE = 7
}
& $env:TEST_SCRIPT init -ExternalDb
exit $LASTEXITCODE
'''
        environment = {**os.environ, "TEST_ARGUMENT_FILE": str(self.arguments), "TEST_SCRIPT": str(script)}
        result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                                env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        arguments = json.loads(self.arguments.read_text(encoding="utf-8-sig"))
        self.assertEqual(arguments[:4], ["run", "--locked", "--inexact", "--project"])
        self.assertEqual(Path(arguments[4]), self.root / "backend")
        self.assertEqual(Path(arguments[6]), self.root / "scripts/service_manager.py")
        self.assertEqual(arguments[7:], ["init", "--external-db"])

    @unittest.skipUnless(BASH, "Bash is not installed")
    def test_unix_wrappers_forward_options_and_preserve_exit_status(self):
        bootstrap = self.root / "shell-environment"
        bootstrap.write_text('uname() { printf "%s\\n" "$TEST_OS"; }\n', encoding="utf-8")
        executable = self.root / "uv"
        executable.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$TEST_ARGUMENT_FILE"\n'
                              'exit "$TEST_EXIT_CODE"\n', encoding="utf-8")
        executable.chmod(0o755)
        for platform, name in (("Linux", "service-linux.sh"), ("Darwin", "service-macos.sh")):
            script = self.root / "scripts" / name
            shutil.copyfile(ROOT / "scripts" / name, script)
            for supplied, expected in (([], ["start"]), (["init", "--external-db"], ["init", "--external-db"])):
                with self.subTest(platform=platform, arguments=supplied):
                    environment = {
                        **os.environ, "TEST_OS": platform, "BASH_ENV": bootstrap.as_posix(),
                        "TEST_ARGUMENT_FILE": self.arguments.as_posix(), "TEST_EXIT_CODE": "9",
                        "PATH": str(self.root) + os.pathsep + os.environ.get("PATH", ""),
                    }
                    result = subprocess.run([BASH, script.as_posix(), *supplied], env=environment,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 9, result.stdout + result.stderr)
                    arguments = self.arguments.read_text(encoding="utf-8").splitlines()
                    self.assertEqual(arguments[:4], ["run", "--locked", "--inexact", "--project"])
                    self.assertIn(self.root.name, arguments[4])
                    self.assertTrue(arguments[4].endswith("/backend"))
                    self.assertTrue(arguments[6].endswith("/scripts/service_manager.py"))
                    self.assertEqual(arguments[7:], expected)


if __name__ == "__main__":
    unittest.main()
