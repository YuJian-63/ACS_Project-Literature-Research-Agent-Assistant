from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dotenv import dotenv_values, set_key, unset_key
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import service_manager as service
import configure_local

BASH = os.environ.get("ACS_BASH") or shutil.which("bash")


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "backend").mkdir()
        (self.root / "agent").mkdir()
        shutil.copyfile(ROOT / "backend/.env.example", self.root / "backend/.env.example")
        (self.root / "agent/.env.example").write_text("MODEL_NAME=test\n", encoding="utf-8")
        (self.root / ".env.local-research").write_text(
            "SMTP_USERNAME=test@qq.com\nSMTP_AUTH_CODE=test-code\nBAILIAN_API_KEY=test-key\n", encoding="utf-8",
        )
        self.env = self.root / "backend/.env"
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        output = redirect_stdout(StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_fresh_tacc_configuration_matches_compose_and_supports_local_http(self):
        configure_local.configure(self.root)
        settings = service.read_settings(self.root)
        values = dotenv_values(self.env)
        database = make_url(settings.database_url.get_secret_value())
        self.assertEqual(database.username, values["POSTGRES_USER"])
        self.assertEqual(database.database, values["POSTGRES_DB"])
        self.assertEqual(database.port, int(values["POSTGRES_PORT"]))
        self.assertEqual(database.password, values["POSTGRES_PASSWORD"])
        service.validate_configuration(settings)
        service.validate_database(self.root, settings)
        self.assertTrue(settings.agent_dispatch_enabled)
        self.assertEqual(settings.agent_transport, "tcloud")
        self.assertFalse(settings.evaluation_enabled)

    def test_reconfigure_keeps_existing_database_keys_and_backend_tavily_key(self):
        service.prepare_configuration(self.root)
        set_key(str(self.env), "TAVILY_API_KEY", "backend-search-key")
        original = dotenv_values(self.env)
        configure_local.configure(self.root)
        configure_local.configure(self.root)
        updated = dotenv_values(self.env)
        for key in (*service.SECRET_KEYS, "DATABASE_URL", "POSTGRES_PASSWORD", "STORAGE_ROOT", "TAVILY_API_KEY"):
            self.assertEqual(updated[key], original[key], key)

    def test_missing_local_flags_keep_safe_runtime_defaults(self):
        service.prepare_configuration(self.root)
        for key in ("AUTH_COOKIE_SECURE", "EVALUATION_ENABLED"):
            unset_key(str(self.env), key)
        configure_local.configure(self.root)
        settings = service.read_settings(self.root)
        self.assertFalse(settings.auth_cookie_secure)
        self.assertFalse(settings.evaluation_enabled)

    def test_reconfigure_preserves_an_enabled_and_configured_evaluation(self):
        service.prepare_configuration(self.root)
        for name, value in (("EVALUATION_ENABLED", "true"), ("EVALUATION_API_KEY", "test-key"),
                            ("EVALUATION_MODEL", "test-model")):
            set_key(str(self.env), name, value)
        configure_local.configure(self.root)
        settings = service.read_settings(self.root)
        self.assertTrue(settings.evaluation_configured)
        self.assertEqual(settings.evaluation_model, "test-model")

    def test_configuration_refuses_to_run_while_another_launcher_holds_the_lock(self):
        service.prepare_configuration(self.root)
        original = self.env.read_bytes()
        with service.service_lock(self.root / "backend/runtime/service.lock"):
            with self.assertRaises(service.ServiceError):
                configure_local.configure(self.root)
        self.assertEqual(self.env.read_bytes(), original)


@unittest.skipUnless(BASH, "Bash is required for legacy launcher checks")
class ShellTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="legacy launch ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for folder in ("scripts", "backend/.venv/bin", "frontend/node_modules/vite/bin", "bin"):
            (self.root / folder).mkdir(parents=True)
        for name in ("research", "local-research", "service_manager.py"):
            shutil.copyfile(ROOT / "scripts" / name, self.root / "scripts" / name)
        shutil.copyfile(ROOT / "backend/.env.example", self.root / "backend/.env.example")
        (self.root / "frontend/node_modules/vite/bin/vite.js").touch()
        self.trace = self.root / "trace.txt"
        bootstrap = self.root / "shell-environment"
        bootstrap.write_text('if command -v cygpath >/dev/null 2>&1; then TEST_BIN=$(cygpath -u "$TEST_BIN"); fi\n'
                             'export PATH="$TEST_BIN:$PATH"\nhash -r\n', encoding="utf-8")
        self.environment = {**os.environ, "TEST_TRACE": self.trace.as_posix(),
                            "BASH_ENV": bootstrap.as_posix(), "TEST_BIN": (self.root / "bin").as_posix(),
                            "PYTHONIOENCODING": "utf-8",
                            "TEST_REAL_PYTHON": sys.executable,
                            "PATH": str(self.root / "bin") + os.pathsep + os.environ.get("PATH", "")}
        for key in service.Settings.model_fields:
            self.environment.pop(key.upper(), None)

    def executable(self, path, body):
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)

    def run_shell(self, script, *, command=False, arguments=(), environment=None):
        args = [BASH, "-c", script, (self.root / "scripts/local-research").as_posix()] if command else [BASH, str(script)]
        return subprocess.run([*args, *arguments], env=environment or self.environment,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)

    def test_local_start_migrates_before_services_and_aborts_on_migration_error(self):
        self.executable(self.root / "backend/.venv/bin/python", r'''
printf '%s\n' "$*" >> "$TEST_TRACE"
if [[ "$*" == '-m alembic upgrade head' ]]; then exit "${FAIL_MIGRATION:-0}"; fi
if [[ "${1:-}" == - ]]; then cat >/dev/null; fi
''')
        self.executable(self.root / "bin/docker", 'printf "docker %s\\n" "$*" >> "$TEST_TRACE"')
        prefix = (ROOT / "scripts/local-research").read_text(encoding="utf-8").split("\npids=()", 1)[0]
        for fail in ("0", "9"):
            with self.subTest(migration_exit=fail):
                self.trace.unlink(missing_ok=True)
                result = self.run_shell(prefix + '\nprintf "APPLICATION_START\\n" >> "$TEST_TRACE"', command=True,
                                        environment={**self.environment, "FAIL_MIGRATION": fail})
                commands = self.trace.read_text(encoding="utf-8").splitlines()
                self.assertIn("-m alembic upgrade head", commands)
                self.assertLess(commands.index("docker compose up -d --wait postgres"), commands.index("-m alembic upgrade head"))
                self.assertEqual(result.returncode, int(fail), result.stderr)
                self.assertEqual("APPLICATION_START" in commands, fail == "0")

    def test_evaluation_worker_starts_only_when_configured(self):
        source = (ROOT / "scripts/local-research").read_text(encoding="utf-8")
        workers = source.split('start parser "$python"', 1)[1].split("web_server() {", 1)[0]
        workers = 'start parser "$python"' + workers
        for enabled in ("0", "1"):
            with self.subTest(enabled=enabled):
                script = r'''
start() { printf '%s\n' "$1"; }
python() { [[ "$*" == *evaluation_configured* && "$ENABLE_EVALUATION" == 1 ]]; }
python=python
''' + workers
                result = self.run_shell(script, command=True,
                                        environment={**self.environment, "ENABLE_EVALUATION": enabled})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual("evaluation" in result.stdout.splitlines(), enabled == "1")

    def test_evaluation_logs_are_supported(self):
        logs = self.root / "backend/runtime/local-research"
        logs.mkdir(parents=True)
        (logs / "evaluation.log").touch()
        self.executable(self.root / "bin/tail", 'printf "%s\\n" "$*"')
        result = self.run_shell(self.root / "scripts/local-research", arguments=("logs", "evaluation"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("evaluation.log", result.stdout)

    def ecs_configuration(self, **updates):
        with patch.dict(os.environ, {}, clear=True):
            service.prepare_configuration(self.root)
        for key, value in {"FRONTEND_PUBLIC_URL": "https://example.com", "AUTH_COOKIE_SECURE": "true", **updates}.items():
            set_key(str(self.root / "backend/.env"), key, value)
        self.executable(self.root / "backend/.venv/bin/python", 'exec "$TEST_REAL_PYTHON" "$@"')
        self.executable(self.root / "bin/curl", "exit 0")
        self.executable(self.root / "bin/systemctl", r'''
if [[ "$1" == list-unit-files ]]; then
  unit="${@: -1}"
  if [[ "$unit" != "${MISSING_UNIT:-}" ]]; then printf '%s enabled\n' "$unit"; fi
elif [[ "$1" == start ]]; then
  printf '%s\n' "$*" >> "$TEST_TRACE"
fi
''')

    def test_ecs_starts_configured_evaluation_worker(self):
        self.ecs_configuration(AGENT_LIBRARY_PUBLIC_URL="https://library.example.com", EVALUATION_ENABLED="true",
                               EVALUATION_API_KEY="test-key", EVALUATION_MODEL="test-model")
        result = self.run_shell(self.root / "scripts/research", arguments=("up",))
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.trace.read_text(encoding="utf-8")
        self.assertIn("acs-evaluation.service", commands)
        self.assertNotIn("acs-runner.service", commands)

    def test_ecs_without_dispatch_does_not_require_a_public_library_url(self):
        self.ecs_configuration()
        result = self.run_shell(self.root / "scripts/research", arguments=("up",))
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.trace.read_text(encoding="utf-8")
        self.assertIn("acs-parser.service", commands)
        for unit in ("acs-runner.service", "acs-import.service", "acs-mail.service", "acs-evaluation.service"):
            self.assertNotIn(unit, commands)

    def test_missing_enabled_worker_unit_is_reported_before_starting_api(self):
        self.ecs_configuration(AGENT_LIBRARY_PUBLIC_URL="https://library.example.com", EVALUATION_ENABLED="true",
                               EVALUATION_API_KEY="test-key", EVALUATION_MODEL="test-model")
        result = self.run_shell(self.root / "scripts/research", arguments=("up",),
                                environment={**self.environment, "MISSING_UNIT": "acs-evaluation.service"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("acs-evaluation.service", result.stderr)
        self.assertFalse(self.trace.exists())


if __name__ == "__main__":
    unittest.main()
