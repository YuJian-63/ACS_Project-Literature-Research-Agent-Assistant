"""HTTP + real read_evidence queries; SQLite fixtures do not test PostgreSQL constraints."""

import hashlib
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Column, JSON, MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.models import Paper, PaperChunk
from app.main import create_app


class EvidenceAPITests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        # Portable fixture schema only: production PostgreSQL DDL is intentionally not migrated here.
        metadata = MetaData()
        for table in Base.metadata.sorted_tables:
            Table(table.name, metadata, *(Column(column.name, JSON() if isinstance(column.type, JSONB)
                                                else column.type, primary_key=column.primary_key)
                                          for column in table.columns))
        metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine)
        self.paper_id = uuid4()
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.add(Paper(id=self.paper_id, title="Fixture", original_filename="fixture.pdf",
                              storage_key=f"uploads/{self.paper_id}.pdf", content_type="application/pdf",
                              size_bytes=100, sha256="a" * 64, status="ready", page_count=104,
                              parser_version="fixture-v1", created_at=now, updated_at=now))
            for index in range(104):
                content = f"原文 evidence {index}\nExact text."
                session.add(PaperChunk(id=uuid4(), paper_id=self.paper_id, chunk_index=index,
                                       page_number=index + 1, content=content,
                                       content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                                       parser_version="fixture-v1", created_at=now))
        settings = Settings(database_url="postgresql+psycopg://fixture:fixture@127.0.0.1/fixture",
                            task_monitor_enabled=False)
        self.app = create_app(settings)
        self.app.state.sessions = self.sessions
        # No lifespan: no real database engine, monitor, network client or migration runs.
        self.client = TestClient(self.app)
        self.path = f"/api/v1/papers/{self.paper_id}/evidence"

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_default_pagination_and_exact_source_fields(self):
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertIn("x-request-id", response.headers)
        page = response.json()
        self.assertEqual(page["paper_id"], str(self.paper_id))
        self.assertEqual(page["paper_sha256"], "a" * 64)
        self.assertEqual(page["page_count"], 104)
        self.assertEqual(page["parser_version"], "fixture-v1")
        self.assertEqual(len(page["items"]), 100)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_after_index"], 99)
        item = page["items"][0]
        self.assertEqual(set(item), {"chunk_id", "paper_id", "chunk_index", "page_number", "content", "content_sha256", "parser_version"})
        self.assertEqual(item["content"], "原文 evidence 0\nExact text.")
        self.assertEqual(item["content_sha256"], hashlib.sha256(item["content"].encode()).hexdigest())
        self.assertEqual(item["page_number"], 1)
        tail = self.client.get(self.path, params={"after_index": page["next_after_index"]}).json()
        self.assertEqual([item["chunk_index"] for item in tail["items"]], [100, 101, 102, 103])
        self.assertFalse(tail["has_more"])
        self.assertEqual(tail["next_after_index"], 103)

    def test_small_page_and_empty_page(self):
        page = self.client.get(self.path, params={"after_index": -1, "limit": 1}).json()
        self.assertEqual([item["chunk_index"] for item in page["items"]], [0])
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_after_index"], 0)
        for cursor in (103, 999):
            page = self.client.get(self.path, params={"after_index": cursor}).json()
            self.assertEqual(page["items"], [])
            self.assertFalse(page["has_more"])
            self.assertEqual(page["next_after_index"], cursor)

    def test_missing_and_not_ready(self):
        response = self.client.get(f"/api/v1/papers/{uuid4()}/evidence")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "PAPER_NOT_FOUND")
        for status in ("uploaded", "processing", "failed"):
            with self.subTest(status=status):
                with self.sessions.begin() as session:
                    session.get(Paper, self.paper_id).status = status
                response = self.client.get(self.path)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], "PAPER_NOT_READY")

    def test_invalid_parameters(self):
        for params in ({"limit": 0}, {"limit": 101}, {"limit": "abc"}, {"limit": "1.5"},
                       {"after_index": -2}, {"after_index": "abc"}, {"after_index": "1.5"}):
            with self.subTest(params=params):
                response = self.client.get(self.path, params=params)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        response = self.client.get("/api/v1/papers/not-a-uuid/evidence")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_openapi_contract(self):
        spec = self.client.get("/openapi.json").json()
        operation = spec["paths"]["/api/v1/papers/{paper_id}/evidence"]["get"]
        self.assertEqual(operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
                         "#/components/schemas/EvidencePage")
        params = {item["name"]: item["schema"] for item in operation["parameters"]}
        self.assertEqual(params["after_index"]["default"], -1)
        self.assertEqual(params["after_index"]["minimum"], -1)
        self.assertEqual(params["limit"]["default"], 100)
        self.assertEqual(params["limit"]["maximum"], 100)


if __name__ == "__main__":
    unittest.main()
