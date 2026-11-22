import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/service_manager.py"
service = None
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location("service_manager", SOURCE)
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(service, "The shared service launcher is not implemented")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        backend = self.root / "backend"
        backend.mkdir()
        (backend / ".env.example").write_bytes((ROOT / "backend/.env.example").read_bytes())
        self.env = backend / ".env"
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def configure(self, **values):
        service.prepare_configuration(self.root)
        for key, value in values.items():
            set_key(str(self.env), key, str(value))
        return service.read_settings(self.root)

    def test_new_configuration_is_usable_locally_and_matches_compose(self):
        settings = self.configure()
        values = dotenv_values(self.env)
        self.assertFalse(settings.auth_cookie_secure)
        self.assertFalse(settings.agent_dispatch_enabled)
        self.assertFalse(settings.arxiv_enabled)
        self.assertFalse(settings.evaluation_enabled)
        self.assertEqual(settings.frontend_public_url, "http://127.0.0.1:5173")
        self.assertEqual(len({values[key] for key in service.SECRET_KEYS}), 3)
        for key in ("AUTH_RATE_KEY", "AUTH_CSRF_KEY"):
            self.assertGreaterEqual(len(values[key].encode()), 32)
        Fernet(values["MAIL_OUTBOX_KEY"].encode())
        service.validate_configuration(settings)
        service.validate_database(self.root, settings)
        if os.name != "nt":
            self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)

    def test_existing_values_comments_and_keys_are_preserved_on_repeated_init(self):
        settings = self.configure(AUTH_COOKIE_SECURE="true", FRONTEND_PUBLIC_URL="https://example.com")
        with self.env.open("a", encoding="utf-8") as output:
            output.write("\n# User setting\nCUSTOM_VALUE='keep this'\n")
        original = self.env.read_bytes()
        service.prepare_configuration(self.root)
        self.assertEqual(self.env.read_bytes(), original)
        self.assertEqual(service.read_settings(self.root).auth_rate_key, settings.auth_rate_key)

    def test_fill_missing_secret_without_rotating_other_credentials(self):
        settings = self.configure()
        set_key(str(self.env), "AUTH_CSRF_KEY", "")
        set_key(str(self.env), "SMTP_AUTH_CODE", "private-existing-code")
        service.prepare_configuration(self.root)
        result = dotenv_values(self.env)
        self.assertEqual(result["AUTH_RATE_KEY"], settings.auth_rate_key.get_secret_value())
        self.assertEqual(result["MAIL_OUTBOX_KEY"], settings.mail_outbox_key.get_secret_value())
        self.assertEqual(result["SMTP_AUTH_CODE"], "private-existing-code")
        self.assertGreaterEqual(len(result["AUTH_CSRF_KEY"]), 32)

    def test_workers_follow_feature_configuration_including_evaluation(self):
        self.assertEqual(service.worker_modules(self.configure()), [("parser", "app.parser_worker")])
        settings = self.configure(
            SMTP_HOST="smtp.qq.com", SMTP_USERNAME="test@qq.com", SMTP_FROM="test@qq.com",
            SMTP_AUTH_CODE="secret", AGENT_DISPATCH_ENABLED="true", ARXIV_ENABLED="true",
            ARXIV_CONTACT_EMAIL="test@example.com", EVALUATION_ENABLED="true",
            EVALUATION_API_KEY="secret", EVALUATION_MODEL="deepseek-test",
        )
        service.validate_configuration(settings)
        self.assertEqual(dict(service.worker_modules(settings)), {
            "parser": "app.parser_worker", "mail": "app.mail_worker",
            "runner": "app.runner_worker", "imports": "app.import_worker",
            "evaluation": "app.evaluation_worker",
        })

    def test_incomplete_enabled_features_fail_with_actionable_field_names(self):
        for values, field in (
            ({"EVALUATION_ENABLED": "true"}, "EVALUATION"),
            ({"ARXIV_ENABLED": "true"}, "ARXIV_CONTACT_EMAIL"),
            ({"SMTP_USERNAME": "test@qq.com"}, "SMTP"),
            ({"AUTH_COOKIE_SECURE": "true"}, "AUTH_COOKIE_SECURE"),
        ):
            with self.subTest(field=field):
                settings = self.configure(**values)
                with self.assertRaisesRegex(service.ServiceError, field):
                    service.validate_configuration(settings)
                self.env.unlink()

    def test_compose_mismatch_is_rejected_before_starting_database(self):
        settings = self.configure(POSTGRES_PORT="55555")
        with self.assertRaisesRegex(service.ServiceError, "DATABASE_URL"):
            service.validate_database(self.root, settings)

    def test_environment_overrides_are_checked_consistently(self):
        self.configure()
        with patch.dict(os.environ, {"POSTGRES_PASSWORD": "different-secret"}):
            with self.assertRaises(service.ServiceError) as raised:
                service.validate_database(self.root, service.read_settings(self.root))
        self.assertNotIn("different-secret", str(raised.exception))

    def test_initialization_orders_database_before_migration_and_never_deletes_volumes(self):
        with patch.object(service, "require_tools"), patch.object(service, "run_command") as run:
            service.initialize(self.root, external_db=False)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][1:], ["ci"])
        self.assertEqual(commands[1], ["docker", "compose", "up", "-d", "--wait", "postgres"])
        self.assertEqual(commands[2][-3:], ["alembic", "upgrade", "head"])
        self.assertFalse(any("down" in command for command in commands))

    def test_external_database_skips_docker(self):
        self.configure(DATABASE_URL="postgresql+psycopg://user:password@db.example:5432/app")
        with patch.object(service, "require_tools"), patch.object(service, "run_command") as run:
            service.initialize(self.root, external_db=True)
        self.assertFalse(any("docker" in call.args[0] for call in run.call_args_list))

    def test_start_brings_up_compose_unless_external_database_is_selected(self):
        self.configure()
        vite = self.root / "frontend/node_modules/vite/bin/vite.js"
        vite.parent.mkdir(parents=True)
        vite.touch()
        for external in (False, True):
            with self.subTest(external=external):
                with (patch.object(service, "require_tools"),
                      patch.object(service, "run_command") as run,
                      patch.object(service.socket, "socket"),
                      patch.object(service, "ProcessManager") as processes):
                    manager = processes.return_value.__enter__.return_value
                    manager.check.side_effect = service.ServiceError("stop test")
                    with self.assertRaisesRegex(service.ServiceError, "stop test"):
                        service.start_services(self.root, external_db=external)
                if external:
                    run.assert_not_called()
                else:
                    run.assert_called_once_with(
                        ["docker", "compose", "up", "-d", "--wait", "postgres"], self.root / "backend",
                    )
                names = [call.args[0] for call in manager.start.call_args_list]
                self.assertEqual(names, ["api", "parser", "web"])

    def test_database_boot_failure_prevents_starting_application_services(self):
        self.configure()
        vite = self.root / "frontend/node_modules/vite/bin/vite.js"
        vite.parent.mkdir(parents=True)
        vite.touch()
        with (patch.object(service, "require_tools"),
              patch.object(service.socket, "socket"),
              patch.object(service, "ProcessManager") as processes,
              patch.object(service, "run_command", side_effect=service.ServiceError("database unavailable"))):
            processes.return_value.__enter__.return_value.check.side_effect = service.ServiceError("stop test")
            with self.assertRaisesRegex(service.ServiceError, "database unavailable"):
                service.start_services(self.root)
        processes.assert_not_called()


@unittest.skipUnless(service, "Shared launcher not implemented yet")
class ProcessTests(unittest.TestCase):
    def test_lock_blocks_duplicate_launcher_and_releases_after_error(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "service.lock"
            with self.assertRaisesRegex(RuntimeError, "test failure"):
                with service.service_lock(lock):
                    with self.assertRaises(service.ServiceError):
                        with service.service_lock(lock):
                            self.fail("Duplicate launcher acquired the lock")
                    raise RuntimeError("test failure")
            with service.service_lock(lock):
                pass

    def test_child_is_stopped_when_another_service_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = service.ProcessManager(Path(directory))
            with self.assertRaises(service.ServiceError):
                with manager:
                    child = manager.start("sleeper", [sys.executable, "-c", "import time; time.sleep(120)"], Path(directory))
                    failed = manager.start("failure", [sys.executable, "-c", "raise SystemExit(7)"], Path(directory))
                    failed.wait(timeout=10)
                    manager.check()
            self.assertIsNotNone(child.poll())

    def test_readiness_timeout_cleans_up_owned_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(service.ServiceError, "readiness"):
                with service.ProcessManager(Path(directory)) as manager:
                    child = manager.start("sleeper", [sys.executable, "-c", "import time; time.sleep(120)"], Path(directory))
                    with patch.object(service, "urlopen", side_effect=OSError("offline")):
                        manager.wait_ready("http://127.0.0.1/ready", timeout=0.01)
            self.assertIsNotNone(child.poll())


if __name__ == "__main__":
    unittest.main()
