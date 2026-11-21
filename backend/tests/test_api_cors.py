import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app, create_library_app


class CorsContractTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Settings(_env_file=None,
            database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
            task_monitor_enabled=False))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_allowed_origin_can_preflight_authenticated_delete(self):
        for path in ("/api/v1/tasks/00000000-0000-0000-0000-000000000001",
                     "/api/v1/papers/00000000-0000-0000-0000-000000000001"):
            with self.subTest(path=path):
                response = self.client.options(path, headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "DELETE",
                    "Access-Control-Request-Headers": "x-csrf-token",
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-credentials"], "true")
                self.assertIn("DELETE", response.headers["access-control-allow-methods"])

    def test_other_origins_remain_disallowed(self):
        response = self.client.options("/api/v1/tasks/fixture", headers={
            "Origin": "https://other.example.org",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "x-csrf-token",
        })
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)


class LibraryTunnelTests(unittest.TestCase):
    def test_tunnel_only_exposes_bearer_reads_and_health(self):
        settings = Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1:1/unused",
            task_monitor_enabled=True, auth_rate_key="r" * 32, auth_csrf_key="c" * 32)
        app = create_library_app(settings)
        paths = app.openapi()["paths"]
        base = "/api/v1/agent/papers"
        self.assertEqual({path: set(methods) for path, methods in paths.items()},
            {"/health": {"get"}, base: {"get"}, base + "/{paper_id}/pdf": {"get"}})
        with patch("app.main.TaskMonitor", side_effect=AssertionError("Unexpected monitor")), TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            client.cookies.set("lra_dev_session", "browser-session")
            client.headers.update({"Origin": settings.frontend_public_url, "X-CSRF-Token": "browser-token"})
            for path in (base, base + "/00000000-0000-4000-8000-000000000001/pdf"):
                response = client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertIn("Bearer", response.headers["www-authenticate"])
                self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(client.post("/api/v1/agent/library-token").status_code, 404)
            self.assertEqual(client.post(base).status_code, 405)
            self.assertEqual(client.options(base).status_code, 405)
            for path in ("/docs", "/redoc", "/openapi.json", "/ready", "/api/v1/agent-research", "/api/v1/auth/me"):
                self.assertEqual(client.get(path).status_code, 404, path)
