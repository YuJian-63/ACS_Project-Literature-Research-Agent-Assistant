import unittest

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class CorsContractTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Settings(_env_file=None,
            database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/literature_v3_test_unused",
            task_monitor_enabled=False))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_allowed_origin_can_preflight_authenticated_delete(self):
        for path in ("/api/v1/tasks/00000000-0000-0000-0000-000000000001",
                     "/api/v1/papers/00000000-0000-0000-0000-000000000001"):
            with self.subTest(path=path):
                response = self.client.options(path, headers={
                    "Origin": "http://127.0.0.1:5175",
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
