import os
import re
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.schemas import TaskCreate
from app.auth.security import csrf_token, token_hash
from app.config import Settings
from app.db.models import AuthSession, Base, Paper, PaperChunk, PaperImport, PaperSource, Task, TaskPaper, User
from app.main import create_app
from app.reset_data import planned_files, reset
from app.sources.arxiv import ArxivPaper, ArxivPage, DownloadReceipt
from app.sources.imports import claim_import, complete_import, fail_import, retry_import, staging_path, submit_import
from app.tasks.service import submit_task


class ResetFileTests(unittest.TestCase):
    def test_generated_only_and_unknown_file_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            uploads = root / "uploads"
            uploads.mkdir()
            generated = uploads / f"{uuid4()}.pdf"
            generated.write_bytes(b"%PDF-fixture")
            self.assertEqual(planned_files(root), [generated])
            unknown = uploads / "precious.txt"
            unknown.write_text("keep")
            with self.assertRaises(ValueError):
                planned_files(root)
            self.assertTrue(generated.exists())
            self.assertTrue(unknown.exists())


TEST_URL = os.environ.get("OWNERSHIP_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL, "Set OWNERSHIP_TEST_DATABASE_URL to isolated ownership_tests")
class OwnershipPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = make_url(TEST_URL)
        if target.host != "127.0.0.1" or not re.fullmatch(r"ownership_tests(?:_[0-9a-f]{32})?", target.database or ""):
            raise RuntimeError("Use isolated ownership_tests on loopback")
        cls.engine = create_engine(TEST_URL)
        cls.sessions = sessionmaker(cls.engine, expire_on_commit=False)
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with cls.engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.check(config)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as connection:
            names = ", ".join('"' + name + '"' for name in Base.metadata.tables)
            connection.execute(text("TRUNCATE " + names))
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.settings = Settings(_env_file=None, database_url=TEST_URL, storage_root=self.root,
            task_monitor_enabled=False, task_runner="agent", agent_dispatch_enabled=True, auth_rate_key="r" * 32,
            auth_csrf_key="c" * 32, arxiv_enabled=True, arxiv_contact_email="fixture@example.com")
        from cryptography.fernet import Fernet
        self.settings = self.settings.model_copy(update={"smtp_username": "fixture@qq.com", "smtp_from": "fixture@qq.com",
            "smtp_auth_code": __import__("pydantic").SecretStr("fixture-only"),
            "mail_outbox_key": __import__("pydantic").SecretStr(Fernet.generate_key().decode())})
        self.users = []
        self.tokens = []
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        with self.sessions.begin() as session:
            for index in range(2):
                user = User(id=uuid4(), username=f"fixture{index}", username_key=f"fixture{index}",
                    email=f"fixture{index}@example.com", email_key=f"fixture{index}@example.com",
                    password_hash="unused", status="active", email_verified_at=now)
                session.add(user)
                session.flush()
                raw = "fixture-session-token-" + str(uuid4())
                session.add(AuthSession(id=uuid4(), user_id=user.id, token_hash=token_hash(raw), auth_version=1,
                    expires_at=now + timedelta(days=1)))
                self.users.append(user.id)
                self.tokens.append(raw)
        self.clients = []
        application = create_app(self.settings, self.engine, arxiv_client=self.arxiv_fixture())
        for raw in self.tokens:
            client = TestClient(application)
            client.__enter__()
            client.cookies.set("lra_dev_session", raw)
            client.headers.update({"Origin": self.settings.frontend_public_url, "X-CSRF-Token": csrf_token(self.settings, raw)})
            self.clients.append(client)

    def arxiv_fixture(self):
        from unittest.mock import Mock
        source = Mock()
        source.search.return_value = ArxivPage(total=1, offset=0, limit=10, items=[ArxivPaper(
            external_id="1706.03762v1", title="Fixture paper", authors=["Fixture author"],
            abstract="Fixture abstract", published_at=datetime.now(timezone.utc), source_updated_at=datetime.now(timezone.utc),
            categories=["cs.SE"])])
        return source

    def tearDown(self):
        for client in self.clients:
            client.__exit__(None, None, None)
        self.temporary.cleanup()

    def upload(self, index=0):
        response = self.clients[index].post("/api/v1/papers", files={"file": ("fixture.pdf", b"%PDF-fixture", "application/pdf")})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_upload_accepts_50_mb_and_rejects_one_more_byte(self):
        pdf = b'%PDF-' + b' ' * (52_428_800 - 5)
        response = self.clients[0].post('/api/v1/papers', files={'file': ('large.pdf', pdf, 'application/pdf')})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['size_bytes'], 52_428_800)
        paper_id = response.json()['id']
        self.assertEqual((self.root / 'uploads' / f'{paper_id}.pdf').stat().st_size, 52_428_800)
        rejected = self.clients[0].post('/api/v1/papers', files={'file': ('oversized.pdf', pdf + b' ', 'application/pdf')})
        self.assertEqual(rejected.status_code, 413, rejected.text)
        self.assertEqual(rejected.json()['error']['code'], 'FILE_TOO_LARGE')
        self.assertEqual(self.clients[0].get('/api/v1/papers').json()['total'], 1)
        self.assertEqual(len(list((self.root / 'uploads').iterdir())), 1)

    def test_library_search_ignores_case_preserves_literal_matching_and_ownership(self):
        paper_ids = []
        for owner, filename in ((0, 'opaque.pdf'), (0, 'MixedCase-File.pdf'),
                                (0, 'Literal%Value.pdf'), (0, 'Literal_Value.pdf'),
                                (1, 'MixedCase-private.pdf')):
            response = self.clients[owner].post('/api/v1/papers', files={'file': (filename, b'%PDF-fixture', 'application/pdf')})
            self.assertEqual(response.status_code, 201, response.text)
            paper_ids.append(response.json()['id'])
        with self.sessions.begin() as session:
            session.get(Paper, UUID(paper_ids[0])).title = 'MixedCase Title'
        for query in ('mixedcase', 'MIXEDCASE', 'MiXeDcAsE'):
            with self.subTest(query=query):
                response = self.clients[0].get('/api/v1/papers', params={'q': query})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual({paper['id'] for paper in response.json()['items']}, set(paper_ids[:2]))
        for query, expected in (('%', paper_ids[2]), ('_', paper_ids[3])):
            response = self.clients[0].get('/api/v1/papers', params={'q': query})
            self.assertEqual([paper['id'] for paper in response.json()['items']], [expected])
        filtered = self.clients[0].get('/api/v1/papers', params={'q': 'mixedcase', 'status': 'ready'})
        self.assertEqual(filtered.json()['total'], 0)
        first = self.clients[0].get('/api/v1/papers', params={'q': 'mixedcase', 'limit': 1}).json()
        second = self.clients[0].get('/api/v1/papers', params={'q': 'mixedcase', 'limit': 1, 'offset': 1}).json()
        self.assertEqual(first['total'], 2)
        self.assertEqual({first['items'][0]['id'], second['items'][0]['id']}, set(paper_ids[:2]))

    def test_import_accepts_50_mb_and_exposes_paper_title(self):
        import hashlib
        submit_import(self.sessions, 'arxiv', '1706.03762v1', user_id=self.users[0], settings=self.settings)
        job = claim_import(self.sessions, uuid4())
        data = b'%PDF-' + b' ' * (52_428_800 - 5)
        staged = staging_path(self.root, job)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        metadata = self.arxiv_fixture().search.return_value.items[0]
        receipt = DownloadReceipt(size_bytes=52_428_800, sha256=hashlib.sha256(data).hexdigest())
        self.assertTrue(complete_import(self.sessions, job, metadata, receipt, root=self.root))
        response = self.clients[0].get(f'/api/v1/papers/{job.import_id}')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['size_bytes'], 52_428_800)
        self.assertEqual(response.json()['title'], 'Fixture paper')
        self.assertEqual(response.json()['source']['title'], 'Fixture paper')
        self.assertEqual(response.json()['original_filename'], '1706.03762v1.pdf')

    def test_uploaded_pdf_gets_title_after_real_parser_worker(self):
        from app.workers.parser import ParserWorker
        from test_pdf_titles import paper_pdf

        for metadata, expected in (('Verified Uploaded Paper', 'Verified Uploaded Paper'),
                                   (None, 'Evidence-Grounded Research with Language Model Agents')):
            with self.subTest(metadata=metadata):
                uploaded = self.clients[0].post('/api/v1/papers',
                    files={'file': ('2604.24212v1.pdf', paper_pdf(metadata), 'application/pdf')})
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                self.assertTrue(ParserWorker(self.sessions, self.settings).run_once())
                response = self.clients[0].get('/api/v1/papers/' + uploaded.json()['id'])
                self.assertEqual(response.json()['status'], 'ready', response.text)
                self.assertEqual(response.json()['title'], expected)
                self.assertEqual(response.json()['original_filename'], '2604.24212v1.pdf')
                with self.sessions() as session:
                    self.assertIsNone(session.scalar(select(PaperChunk.id)))
                found = self.clients[0].get('/api/v1/papers', params={'q': expected.lower()}).json()
                self.assertIn(uploaded.json()['id'], [paper['id'] for paper in found['items']])

    def test_metadata_processing_preserves_archived_chunks_without_creating_new_ones(self):
        import hashlib
        from app.workers.parser import ParserWorker
        from test_pdf_titles import paper_pdf

        uploaded = self.clients[0].post('/api/v1/papers',
            files={'file': ('historical.pdf', paper_pdf('Metadata only'), 'application/pdf')}).json()
        paper_id, chunk_id = UUID(uploaded['id']), uuid4()
        content = 'Historical evidence'
        with self.sessions.begin() as session:
            session.add(PaperChunk(id=chunk_id, paper_id=paper_id, chunk_index=0, page_number=1,
                content=content, content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                parser_version='historical-text-v1'))
        self.assertTrue(ParserWorker(self.sessions, self.settings).run_once())
        with self.sessions() as session:
            paper = session.get(Paper, paper_id)
            self.assertEqual((paper.status, paper.title), ('ready', 'Metadata only'))
            chunks = list(session.scalars(select(PaperChunk).where(PaperChunk.paper_id == paper_id)))
            self.assertEqual([(chunk.id, chunk.content, chunk.parser_version) for chunk in chunks],
                [(chunk_id, content, 'historical-text-v1')])

    def test_missing_pdf_title_keeps_uploaded_filename_fallback(self):
        from app.workers.parser import ParserWorker
        from test_pdf_titles import paper_pdf

        uploaded = self.clients[0].post('/api/v1/papers',
            files={'file': ('fallback-name.pdf', paper_pdf('Untitled', heading=False), 'application/pdf')}).json()
        self.assertTrue(ParserWorker(self.sessions, self.settings).run_once())
        response = self.clients[0].get('/api/v1/papers/' + uploaded['id'])
        self.assertEqual(response.json()['status'], 'ready', response.text)
        self.assertEqual(response.json()['title'], 'fallback-name')

    def test_parser_preserves_verified_arxiv_title(self):
        import hashlib
        from app.workers.parser import ParserWorker
        from test_pdf_titles import paper_pdf

        submit_import(self.sessions, 'arxiv', '1706.03762v1', user_id=self.users[0], settings=self.settings)
        job = claim_import(self.sessions, uuid4())
        data = paper_pdf('Different PDF Metadata')
        staged = staging_path(self.root, job)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        receipt = DownloadReceipt(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertTrue(complete_import(self.sessions, job,
            self.arxiv_fixture().search.return_value.items[0], receipt, root=self.root))
        self.assertTrue(ParserWorker(self.sessions, self.settings).run_once())
        response = self.clients[0].get(f'/api/v1/papers/{job.import_id}')
        self.assertEqual(response.json()['status'], 'ready', response.text)
        self.assertEqual(response.json()['title'], 'Fixture paper')

    def test_refresh_existing_uploaded_titles_preserves_evidence_and_supports_dry_run(self):
        from app.papers.refresh_titles import refresh_titles
        from app.workers.parser import ParserWorker
        from test_pdf_titles import paper_pdf

        uploaded = self.clients[0].post('/api/v1/papers',
            files={'file': ('old-upload.pdf', paper_pdf('Existing PDF Research Title'), 'application/pdf')}).json()
        self.assertTrue(ParserWorker(self.sessions, self.settings).run_once())
        paper_id = UUID(uploaded['id'])
        with self.sessions.begin() as session:
            session.get(Paper, paper_id).title = 'old-upload'
            import hashlib
            archived_text = 'Previously extracted evidence must remain available.'
            session.add(PaperChunk(paper_id=paper_id, chunk_index=0, page_number=1,
                content=archived_text, content_sha256=hashlib.sha256(archived_text.encode()).hexdigest(),
                parser_version='historical-text-v1'))
            session.flush()
            evidence = list(session.execute(select(PaperChunk.id, PaperChunk.content, PaperChunk.content_sha256)))
        preview = refresh_titles(self.sessions, self.settings)
        self.assertEqual(preview, {'candidates': 1, 'titles_found': 1, 'updated': 0, 'failed': 0})
        self.assertEqual(self.clients[0].get('/api/v1/papers/' + str(paper_id)).json()['title'], 'old-upload')
        repaired = refresh_titles(self.sessions, self.settings, execute=True)
        self.assertEqual(repaired['updated'], 1)
        response = self.clients[0].get('/api/v1/papers/' + str(paper_id))
        self.assertEqual(response.json()['title'], 'Existing PDF Research Title')
        self.assertEqual(response.json()['sha256'], uploaded['sha256'])
        self.assertEqual(response.json()['status'], 'ready')
        with self.sessions() as session:
            self.assertEqual(list(session.execute(select(PaperChunk.id, PaperChunk.content, PaperChunk.content_sha256))), evidence)
        self.assertEqual(refresh_titles(self.sessions, self.settings, execute=True)['candidates'], 0)

    def test_refresh_titles_preserves_custom_titles_and_rejects_changed_pdf(self):
        from app.papers.refresh_titles import refresh_titles
        from app.workers.parser import ParserWorker
        from test_pdf_titles import paper_pdf

        uploaded = self.clients[0].post('/api/v1/papers',
            files={'file': ('old-upload.pdf', paper_pdf('Research Title'), 'application/pdf')}).json()
        self.assertTrue(ParserWorker(self.sessions, self.settings).run_once())
        paper_id = UUID(uploaded['id'])
        with self.sessions.begin() as session:
            session.get(Paper, paper_id).title = 'Keep This Custom Title'
        self.assertEqual(refresh_titles(self.sessions, self.settings, execute=True)['candidates'], 0)
        with self.sessions.begin() as session:
            session.get(Paper, paper_id).title = 'old-upload'
        (self.root / 'uploads' / f'{paper_id}.pdf').write_bytes(paper_pdf('Changed PDF'))
        result = refresh_titles(self.sessions, self.settings, execute=True)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['updated'], 0)
        self.assertEqual(self.clients[0].get('/api/v1/papers/' + str(paper_id)).json()['title'], 'old-upload')

    def test_agent_search_and_download_only_the_authenticated_library(self):
        import hashlib

        pdf = b"%PDF-agent-library-fixture"
        paper_ids = []
        for index, name in ((0, "Research % draft.pdf"), (0, "Research other.pdf"),
                            (1, "Research % private.pdf")):
            upload = self.clients[index].post("/api/v1/papers", files={"file": (name, pdf, "application/pdf")})
            self.assertEqual(upload.status_code, 201, upload.text)
            paper_ids.append(upload.json()["id"])

        browser = self.clients[0]
        grant = browser.post("/api/v1/agent/library-token")
        self.assertEqual(grant.status_code, 200, grant.text)
        self.assertEqual(grant.headers["cache-control"], "no-store")
        headers = {"Authorization": f"Bearer {grant.json()['access_token']}"}
        with TestClient(browser.app) as agent:
            base = "/api/v1/agent/papers"
            self.assertEqual(browser.get(base).status_code, 401)
            self.assertEqual(agent.get(base, headers=headers, params={"q": "\x00"}).status_code, 422)
            first = agent.get(base, headers=headers, params={"q": "research", "limit": 1}).json()
            second = agent.get(base, headers=headers, params={"q": "research", "limit": 1, "offset": 1}).json()
            self.assertEqual(first["total"], 2)
            self.assertEqual({first["items"][0]["id"], second["items"][0]["id"]}, set(paper_ids[:2]))
            response = agent.get(base, headers=headers, params={"q": "%", "status": "uploaded"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["total"], 1)
            paper = response.json()["items"][0]
            self.assertEqual(paper["id"], paper_ids[0])
            self.assertEqual(paper["title"], "Research % draft")
            self.assertEqual(paper["sha256"], hashlib.sha256(pdf).hexdigest())
            self.assertEqual(paper["size_bytes"], len(pdf))
            download = agent.get(paper["download_url"], headers=headers)
            self.assertEqual(download.content, pdf)
            self.assertEqual(download.headers["content-type"], "application/pdf")
            self.assertTrue(download.headers["content-disposition"].startswith("attachment;"))
            self.assertEqual(agent.get(paper["download_url"]).status_code, 401)
            self.assertEqual(agent.get(f"{base}/{paper_ids[2]}/pdf", headers=headers).status_code, 404)
            self.assertEqual(agent.get(f"/api/v1/papers/{paper_ids[0]}/file", headers=headers).status_code, 401)
            self.assertEqual(agent.post("/api/v1/agent/library-token", headers=headers).status_code, 401)
            (self.root / "uploads" / f"{paper_ids[0]}.pdf").unlink()
            missing = agent.get(paper["download_url"], headers=headers)
            self.assertEqual(missing.status_code, 500)
            self.assertEqual(missing.json()["error"]["code"], "FILE_UNAVAILABLE")

    def test_agent_library_matches_all_keywords_across_title_and_filename(self):
        paper_ids = []
        fixtures = (
            (0, "rust_methods.pdf", "Rust Methods"),
            (0, "agent_notes.pdf", "Rust benchmarks"),
            (0, "rust_agent.pdf", "Repository tools"),
            (1, "rust_agent_private.pdf", "Rust Agent private"),
        )
        for index, filename, title in fixtures:
            response = self.clients[index].post(
                "/api/v1/papers", files={"file": (filename, b"%PDF-fixture", "application/pdf")},
            )
            self.assertEqual(response.status_code, 201, response.text)
            paper_id = response.json()["id"]
            paper_ids.append(paper_id)
            with self.sessions.begin() as session:
                session.get(Paper, UUID(paper_id)).title = title

        browser = self.clients[0]
        grant = browser.post("/api/v1/agent/library-token")
        self.assertEqual(grant.status_code, 200, grant.text)
        headers = {"Authorization": f"Bearer {grant.json()['access_token']}"}
        with TestClient(browser.app) as agent:
            base = "/api/v1/agent/papers"
            for query in ("rust agent", "AGENT RUST", "  Rust\t agent\n", "rust agent rust"):
                with self.subTest(query=query):
                    response = agent.get(base, headers=headers, params={"q": query})
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()
                    self.assertEqual(result["total"], 2)
                    self.assertEqual({paper["id"] for paper in result["items"]}, set(paper_ids[1:3]))
            for offset in (0, 1):
                result = agent.get(base, headers=headers, params={"q": "rust agent", "limit": 1, "offset": offset}).json()
                self.assertEqual(result["total"], 2)
                self.assertEqual(len(result["items"]), 1)
            for query in ("rust missing", "rust %", "rust _missing"):
                result = agent.get(base, headers=headers, params={"q": query}).json()
                self.assertEqual(result["total"], 0)
                self.assertEqual(result["items"], [])
            result = agent.get(base, headers=headers, params={"q": "rust agent", "status": "ready"}).json()
            self.assertEqual(result["total"], 0)
            self.assertEqual(agent.get(base, headers=headers, params={"q": " \t\n"}).status_code, 422)

    def test_agent_library_any_keyword_preserves_ownership_status_and_pagination(self):
        paper_ids = []
        for index, filename in (
            (0, "Rust Methods.pdf"), (0, "Agent Tools.pdf"), (0, "Rust Agent.pdf"),
            (0, "Unrelated.pdf"), (1, "Rust Agent private.pdf"),
        ):
            response = self.clients[index].post(
                "/api/v1/papers", files={"file": (filename, b"%PDF-fixture", "application/pdf")},
            )
            self.assertEqual(response.status_code, 201, response.text)
            paper_ids.append(response.json()["id"])
        with self.sessions.begin() as session:
            paper = session.get(Paper, UUID(paper_ids[0]))
            paper.status, paper.page_count, paper.parser_version = "ready", 1, "fixture"

        browser = self.clients[0]
        grant = browser.post("/api/v1/agent/library-token")
        self.assertEqual(grant.status_code, 200, grant.text)
        headers = {"Authorization": f"Bearer {grant.json()['access_token']}"}
        with TestClient(browser.app) as agent:
            base = "/api/v1/agent/papers"
            for mode, expected in (("any", paper_ids[:3]), ("all", [paper_ids[2]])):
                with self.subTest(mode=mode):
                    response = agent.get(base, headers=headers, params={"q": "rUsT AgEnT", "match": mode})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["total"], len(expected))
                    self.assertEqual({paper["id"] for paper in response.json()["items"]}, set(expected))
            pages = []
            for offset in range(3):
                result = agent.get(base, headers=headers, params={"q": "rust agent", "match": "any", "limit": 1, "offset": offset}).json()
                self.assertEqual(result["total"], 3)
                self.assertEqual(len(result["items"]), 1)
                pages.append(result["items"][0]["id"])
            self.assertEqual(set(pages), set(paper_ids[:3]))
            result = agent.get(base, headers=headers, params={"q": "rust agent", "match": "any", "status": "ready"}).json()
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["id"], paper_ids[0])
            for query in ("missing %", "missing _"):
                result = agent.get(base, headers=headers, params={"q": query, "match": "any"}).json()
                self.assertEqual(result["total"], 0)
            for query in (" \t\n", "\x00"):
                self.assertEqual(agent.get(base, headers=headers, params={"q": query, "match": "any"}).status_code, 422)
            self.assertEqual(agent.get(base, headers=headers, params={"match": "any"}).json()["total"], 4)
            self.assertEqual(agent.get(base, headers=headers, params={"q": "rust agent", "match": "invalid"}).status_code, 422)

    def test_agent_library_token_requires_csrf_and_rejects_invalid_expired_or_revoked_tokens(self):
        from datetime import timedelta
        from unittest.mock import patch

        browser = self.clients[0]
        url = "/api/v1/agent/library-token"
        base = "/api/v1/agent/papers"
        self.assertEqual(browser.post(url, headers={"X-CSRF-Token": "invalid"}).status_code, 403)
        grant = browser.post(url)
        self.assertEqual(grant.status_code, 200, grant.text)
        token = grant.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(browser.app) as agent:
            self.assertEqual(agent.get(base, headers=headers).status_code, 200)
            tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
            self.assertEqual(agent.get(base, headers={"Authorization": f"Bearer {tampered}"}).status_code, 401)
            after_expiry = datetime.fromisoformat(grant.json()["expires_at"]) + timedelta(seconds=1)
            with patch("app.auth.agent_library.db_now", return_value=after_expiry):
                self.assertEqual(agent.get(base, headers=headers).status_code, 401)
            with self.sessions.begin() as session:
                user_session = session.scalar(select(AuthSession).where(AuthSession.user_id == self.users[0]))
                user_session.revoked_at = datetime.now(timezone.utc)
            self.assertEqual(agent.get(base, headers=headers).status_code, 401)

    def task(self, paper, index=0, key="same-key"):
        return self.clients[index].post("/api/v1/tasks", json={"task_type": "summary", "question": "Summarize", "paper_ids": [paper]}, headers={"Idempotency-Key": key})

    def test_delete_unused_paper_removes_file_and_is_owner_scoped(self):
        paper = self.upload()
        path = self.root / 'uploads' / f'{paper}.pdf'
        self.assertEqual(self.clients[1].delete('/api/v1/papers/' + paper).status_code, 404)
        self.assertTrue(path.exists())
        response = self.clients[0].delete('/api/v1/papers/' + paper)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertFalse(path.exists())
        self.assertEqual(self.clients[0].get('/api/v1/papers/' + paper).status_code, 404)
        self.assertEqual(self.clients[0].get('/api/v1/papers').json()['total'], 0)

    def test_delete_rejects_referenced_paper(self):
        paper = self.upload()
        self.assertEqual(self.task(paper).status_code, 202)
        response = self.clients[0].delete('/api/v1/papers/' + paper)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'PAPER_IN_USE')
        self.assertTrue((self.root / 'uploads' / f'{paper}.pdf').exists())

    def test_delete_processing_and_csrf_are_guarded(self):
        from app.papers.lifecycle import claim_parse
        self.upload()
        job = claim_parse(self.sessions, uuid4())
        self.assertEqual(self.clients[0].delete('/api/v1/papers/' + str(job)).status_code, 409)
        self.assertEqual(self.clients[0].delete('/api/v1/papers/' + str(job), headers={'X-CSRF-Token': 'wrong'}).status_code, 403)

    def test_deleted_import_can_be_imported_again_and_manual_failure_retry(self):
        import hashlib
        identity = '1706.03762v1'
        submit_import(self.sessions, 'arxiv', identity, user_id=self.users[0], settings=self.settings)
        job = claim_import(self.sessions, uuid4())
        fail_import(self.sessions, job, 'ARXIV_NOT_FOUND', 'source temporarily missing', False)
        retried = retry_import(self.sessions, job.import_id, 1, user_id=self.users[0], settings=self.settings)
        self.assertEqual(retried['status'], 'queued')
        job = claim_import(self.sessions, uuid4())
        data = b'%PDF-delete-fixture'
        staged = staging_path(self.root, job)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        source = self.arxiv_fixture().search.return_value.items[0]
        receipt = DownloadReceipt(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertTrue(complete_import(self.sessions, job, source, receipt, root=self.root))
        self.assertEqual(self.clients[0].delete('/api/v1/papers/' + str(job.import_id)).status_code, 204)
        found = self.clients[0].get('/api/v1/paper-search', params={'q': 'rust'}).json()['items'][0]
        self.assertIsNone(found['import_status'])
        self.assertIsNone(found['paper_id'])
        again = submit_import(self.sessions, 'arxiv', identity, user_id=self.users[0], settings=self.settings)
        self.assertEqual(again['status'], 'queued')
        self.assertNotEqual(again['id'], job.import_id)

    def test_search_import_reuses_verified_metadata_without_second_api_request(self):
        import hashlib
        from unittest.mock import Mock
        from app.workers.imports import ImportWorker
        self.clients[0].get('/api/v1/paper-search', params={'q': 'rust'})
        accepted = self.clients[0].post('/api/v1/paper-imports', json={'provider': 'arxiv', 'external_id': '1706.03762v1'})
        self.assertEqual(accepted.status_code, 202)
        identity = UUID(accepted.json()['id'])
        with self.sessions() as session:
            self.assertEqual(session.get(PaperImport, identity).source_metadata['external_id'], '1706.03762v1')
        client = Mock()
        client.fetch_metadata.side_effect = AssertionError('Search metadata must avoid duplicate API request')
        def download(external_id, destination, **kwargs):
            data = b'%PDF-cached-metadata-fixture'
            destination.write_bytes(data)
            return DownloadReceipt(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        client.download_pdf.side_effect = download
        self.assertTrue(ImportWorker(self.sessions, self.settings, client_factory=lambda *_: client).run_once())
        client.fetch_metadata.assert_not_called()
        with self.sessions() as session:
            self.assertEqual(session.get(PaperImport, identity).status, 'succeeded')
            self.assertEqual(session.get(Paper, identity).source.external_id, '1706.03762v1')
        # Old/direct imports without a snapshot retain exact-version metadata lookup.
        submit_import(self.sessions, 'arxiv', '1706.03762v2', user_id=self.users[0], settings=self.settings)
        client.fetch_metadata.side_effect = None
        client.fetch_metadata.return_value = self.arxiv_fixture().search.return_value.items[0].model_copy(update={'external_id': '1706.03762v2'})
        self.assertTrue(ImportWorker(self.sessions, self.settings, client_factory=lambda *_: client).run_once())
        client.fetch_metadata.assert_called_once_with('1706.03762v2')

    def test_retry_hydrates_legacy_import_from_verified_search_cache(self):
        item = submit_import(self.sessions, 'arxiv', '1706.03762v1', user_id=self.users[0], settings=self.settings)
        job = claim_import(self.sessions, uuid4())
        fail_import(self.sessions, job, 'ARXIV_TIMEOUT', 'arXiv 请求超时', True)
        self.clients[0].get('/api/v1/paper-search', params={'q': 'rust'})
        response = self.clients[0].post('/api/v1/paper-imports/' + str(item['id']) + '/retry', json={'expected_attempt': 1})
        self.assertEqual(response.status_code, 202)
        with self.sessions() as session:
            self.assertEqual(session.get(PaperImport, job.import_id).source_metadata['external_id'], '1706.03762v1')

    def test_delete_task_releases_only_its_own_paper_references(self):
        paper = self.upload()
        first = self.task(paper, key='first').json()['id']
        second = self.task(paper, key='second').json()['id']
        self.assertEqual(self.clients[1].delete('/api/v1/tasks/' + first).status_code, 404)
        self.assertEqual(self.clients[0].delete('/api/v1/tasks/' + first, headers={'X-CSRF-Token': 'wrong'}).status_code, 403)
        self.assertEqual(self.clients[0].delete('/api/v1/tasks/' + first).status_code, 204)
        self.assertEqual(self.clients[0].get('/api/v1/tasks/' + first).status_code, 404)
        self.assertEqual(self.clients[0].delete('/api/v1/papers/' + paper).status_code, 409)
        self.assertEqual(self.clients[0].delete('/api/v1/tasks/' + second).status_code, 204)
        self.assertTrue((self.root / 'uploads' / f'{paper}.pdf').exists())
        self.assertEqual(self.clients[0].delete('/api/v1/papers/' + paper).status_code, 204)

    def test_delete_completed_task_cascades_results_citations_and_events(self):
        from app.db.models import Artifact, Citation, TaskEvent
        from app.tasks.lifecycle import database_time
        paper = UUID(self.upload())
        task_id = UUID(self.task(str(paper)).json()['id'])
        with self.sessions.begin() as session:
            task = session.get(Task, task_id)
            now = database_time(session)
            task.status, task.stage = 'succeeded', 'completed'
            task.started_at = task.finished_at = now
            artifact = Artifact(task_id=task_id, title='Research', content_markdown='Supported answer [C1].')
            session.add(artifact)
            session.flush()
            session.add(Citation(artifact_id=artifact.id, task_id=task_id, citation_key='C1', paper_id=paper,
                chunk_id=None, agent_chunk_id='source:p1:c1', agent_source_id='source',
                page_number=1, quote='A complete source sentence.'))
        self.assertEqual(self.clients[0].delete('/api/v1/tasks/' + str(task_id)).status_code, 204)
        with self.sessions() as session:
            for model in [Task, TaskPaper, Artifact, Citation, TaskEvent]:
                self.assertIsNone(session.scalar(select(model)))
            self.assertIsNotNone(session.get(Paper, paper))
        self.assertEqual(self.clients[0].delete('/api/v1/papers/' + str(paper)).status_code, 204)

    def test_delete_running_task_is_rejected(self):
        from app.tasks.lifecycle import claim_task
        paper = self.upload()
        task_id = self.task(paper).json()['id']
        claim_task(self.sessions, uuid4())
        response = self.clients[0].delete('/api/v1/tasks/' + task_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'TASK_RUNNING')

    def test_agent_budget_is_automatic_and_historical_replay_still_checks_manual_budget(self):
        from app.api.views import task_view
        from app.errors import APIError
        from app.tasks.service import request_hash
        request = TaskCreate(task_type="summary", paper_ids=[self.upload()],
            budget={"max_steps": 1, "max_tokens": 1, "timeout_seconds": 1})
        accepted, _ = submit_task(self.sessions, self.settings, request, "auto-mock", user_id=self.users[0])
        with self.sessions.begin() as session:
            task = session.get(Task, accepted["id"])
            self.assertEqual(task_view(task, request.paper_ids)["budget_mode"], "automatic")
            self.assertGreater(task.max_steps, 1)
            task.runner_type = "mock"
            task.workflow_version = "mock-v1"
            task.run_config = {}
            task.request_hash = request_hash(request)
        request.budget.max_tokens = 2
        with self.assertRaises(APIError) as caught:
            submit_task(self.sessions, self.settings, request, "auto-mock", user_id=self.users[0])
        self.assertEqual(caught.exception.error["code"], "IDEMPOTENCY_CONFLICT")

    def test_reference_sql_matches_current_metadata(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        script = (Path(__file__).resolve().parents[1] / "sql/schema.sql").read_text(encoding="utf-8")
        script = script.removeprefix("BEGIN;").rsplit("COMMIT;", 1)[0]
        with self.engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("CREATE SCHEMA reference_schema"))
                connection.execute(text("SET LOCAL search_path TO reference_schema"))
                connection.exec_driver_sql(script)
                context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
                self.assertEqual(compare_metadata(context, Base.metadata), [])
                self.assertEqual(connection.scalar(text("SELECT count(*) FROM source_request_gates")), 1)
            finally:
                transaction.rollback()

    def test_every_private_route_requires_session(self):
        with TestClient(create_app(self.settings, self.engine)) as client:
            for path in ("papers", "tasks", "paper-imports", "paper-search?q=test"):
                result = client.get("/api/v1/" + path)
                self.assertEqual(result.status_code, 401)
                self.assertEqual(result.headers.get("cache-control"), "no-store")
            self.assertEqual(client.get("/health").status_code, 200)

    def test_cross_user_lists_ids_files_tasks_events_artifacts_are_private(self):
        paper = self.upload()
        result = self.task(paper)
        self.assertEqual(result.status_code, 202, result.text)
        identity = result.json()["id"]
        other = self.clients[1]
        for path in (f"papers/{paper}", f"papers/{paper}/file", f"tasks/{identity}", f"tasks/{identity}/events", f"tasks/{identity}/artifacts"):
            self.assertEqual(other.get("/api/v1/" + path).status_code, 404, path)
        for path in ("papers", "tasks", "paper-imports"):
            self.assertEqual(other.get("/api/v1/" + path).json()["total"], 0)
        self.assertEqual(self.task(paper, index=1).status_code, 404)
        self.assertEqual(self.clients[0].get(f"/api/v1/papers/{paper}/file").content, b"%PDF-fixture")

    def test_same_key_is_scoped_replay_does_not_consume_quota(self):
        first = self.upload()
        second = self.upload(1)
        accepted = self.task(first)
        replay = self.task(first)
        other = self.task(second, index=1)
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(replay.json()["id"], accepted.json()["id"])
        self.assertEqual(other.status_code, 202)
        self.assertNotEqual(other.json()["id"], accepted.json()["id"])
        self.assertEqual(self.task(first, key="second").status_code, 202)
        self.assertEqual(self.task(first, key="third").status_code, 429)
        self.assertEqual(self.task(first).status_code, 202)

    def test_daily_limit_counts_only_new_tasks_and_replays_remain_available(self):
        paper = self.upload()
        self.settings.user_daily_tasks = 1
        first = self.task(paper)
        self.assertEqual(first.status_code, 202)
        rejected = self.task(paper, key="another-key")
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(rejected.json()["error"]["code"], "DAILY_TASK_LIMIT")
        self.assertEqual(self.task(paper).json()["id"], first.json()["id"])

    def test_concurrent_imports_enforce_capacity_without_charging_replay(self):
        def submit(index):
            from app.errors import APIError
            try:
                return submit_import(self.sessions, "arxiv", f"1706.03762v{index + 1}", user_id=self.users[0], settings=self.settings)
            except APIError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        winners = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(winners), 2)
        self.assertEqual(results.count(429), 2)
        replay = submit_import(self.sessions, "arxiv", winners[0]["external_id"], user_id=self.users[0], settings=self.settings)
        self.assertEqual(replay["id"], winners[0]["id"])

    def test_concurrent_tasks_share_one_user_quota_lock(self):
        paper = self.upload()
        body = TaskCreate(task_type="summary", question="Summarize", paper_ids=[paper])
        def submit(index):
            from app.errors import APIError
            try:
                return submit_task(self.sessions, self.settings, body, str(index), user_id=self.users[0])[0]
            except APIError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 2)
        self.assertEqual(results.count(429), 2)

    def test_import_identity_cache_annotations_and_retry_are_scoped(self):
        body = {"provider": "arxiv", "external_id": "1706.03762v1"}
        first = self.clients[0].post("/api/v1/paper-imports", json=body)
        self.assertEqual(first.status_code, 202, first.text)
        identity = first.json()["id"]
        self.assertEqual(self.clients[1].get(f"/api/v1/paper-imports/{identity}").status_code, 404)
        self.assertEqual(self.clients[1].post(f"/api/v1/paper-imports/{identity}/retry", json={"expected_attempt": 1}).status_code, 404)
        self.assertEqual(self.clients[0].get("/api/v1/paper-search?q=fixture").json()["items"][0]["import_id"], identity)
        self.assertIsNone(self.clients[1].get("/api/v1/paper-search?q=fixture").json()["items"][0]["import_id"])
        second = self.clients[1].post("/api/v1/paper-imports", json=body)
        self.assertEqual(second.status_code, 202)
        self.assertNotEqual(second.json()["id"], identity)
        self.assertEqual(self.clients[0].post("/api/v1/paper-imports", json=body).json()["id"], identity)

    def test_mutations_reject_missing_csrf_and_wrong_origin(self):
        client = self.clients[0]
        client.headers.pop("X-CSRF-Token")
        self.assertEqual(client.post("/api/v1/papers", files={"file": ("fixture.pdf", b"%PDF-fixture")}).status_code, 403)
        client.headers["X-CSRF-Token"] = csrf_token(self.settings, self.tokens[0])
        client.headers["Origin"] = "https://evil.example"
        self.assertEqual(client.post("/api/v1/papers", files={"file": ("fixture.pdf", b"%PDF-fixture")}).status_code, 403)

    def test_database_rejects_cross_owner_source_and_task_paper(self):
        paper = UUID(self.upload())
        task = UUID(self.task(str(paper)).json()["id"])
        other_paper = UUID(self.upload(1))
        other_task = UUID(self.task(str(other_paper), index=1).json()["id"])
        with self.sessions() as session:
            paper_sha = session.get(Paper, paper).sha256
            other_sha = session.get(Paper, other_paper).sha256
        with self.assertRaises(IntegrityError), self.sessions.begin() as session:
            session.add(PaperSource(paper_id=paper, user_id=self.users[1], provider="arxiv", external_id="1706.03762v1", source_metadata={}))
        with self.assertRaises(IntegrityError), self.sessions.begin() as session:
            session.add(TaskPaper(task_id=other_task, paper_id=paper, user_id=self.users[1], paper_sha256=paper_sha, selection_order=1))
        with self.assertRaises(IntegrityError), self.sessions.begin() as session:
            session.add(TaskPaper(task_id=task, paper_id=other_paper, user_id=self.users[1], paper_sha256=other_sha, selection_order=1))

    def test_real_auth_router_register_verify_login_and_reset(self):
        from app.auth.mail import decrypt_payload
        from app.db.models import AuthEmailToken, AuthMailOutbox
        from app.auth.security import cookie_name
        from urllib.parse import unquote
        client = self.clients[0]
        password = "a long fixture password"
        credentials = {"username": "RegisteredUser", "email": "new@example.com", "password": password}
        response = client.post("/api/v1/auth/register", json=credentials)
        self.assertEqual(response.status_code, 202, response.text)
        def latest(purpose):
            with self.sessions() as session:
                mail = session.scalar(select(AuthMailOutbox).join(AuthEmailToken, AuthEmailToken.id == AuthMailOutbox.token_id)
                    .where(AuthEmailToken.purpose == purpose).order_by(AuthMailOutbox.created_at.desc()))
                body = decrypt_payload(self.settings, mail.payload_ciphertext)["body"]
                return unquote(body.split("#token=", 1)[1].split()[0])
        self.assertEqual(client.post("/api/v1/auth/verify-email", json={"token": latest("verify_email"), "password": password}).status_code, 200)
        response = client.post("/api/v1/auth/login", json={"username": "registereduser", "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        csrf = response.json()["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf
        raw = response.cookies[cookie_name(self.settings)]
        client.cookies.clear()
        client.cookies.set(cookie_name(self.settings), raw, domain="testserver.local", path="/")
        self.assertEqual(client.get("/api/v1/auth/me").json()["user"]["username"], "RegisteredUser")
        self.upload()
        self.assertEqual(client.get("/api/v1/papers").json()["total"], 1)
        with self.sessions.begin() as session:
            session.execute(text("UPDATE auth_rate_buckets SET expires_at=clock_timestamp()-interval '1 second'"))
        self.assertEqual(client.post("/api/v1/auth/forgot-password", json={"email": "new@example.com"}).status_code, 202)
        token = latest("reset_password")
        response = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "a different long password"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(client.get("/api/v1/papers").status_code, 401)
        self.assertEqual(client.post("/api/v1/auth/reset-password", json={"token": token, "password": "another long password"}).status_code, 400)

    def test_import_worker_inherits_owner_and_retry_replays_at_capacity(self):
        import hashlib
        result = submit_import(self.sessions, "arxiv", "1706.03762v1", user_id=self.users[0], settings=self.settings)
        job = claim_import(self.sessions, uuid4())
        self.assertTrue(fail_import(self.sessions, job, "FIXTURE", "retryable fixture", True))
        retried = retry_import(self.sessions, job.import_id, 1, user_id=self.users[0], settings=self.settings)
        submit_import(self.sessions, "arxiv", "1706.03762v2", user_id=self.users[0], settings=self.settings)
        self.assertEqual(retry_import(self.sessions, job.import_id, 1, user_id=self.users[0], settings=self.settings)["attempt"], 2)
        self.assertEqual(retried["attempt"], 2)
        job = claim_import(self.sessions, uuid4())
        data = b"%PDF-fixture-import"
        staged = staging_path(self.root, job)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        source = self.arxiv_fixture().search.return_value.items[0]
        receipt = DownloadReceipt(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertTrue(complete_import(self.sessions, job, source, receipt, root=self.root))
        with self.sessions() as session:
            paper = session.get(Paper, job.import_id)
            self.assertEqual(paper.user_id, self.users[0])
            self.assertEqual(paper.source.user_id, self.users[0])
        self.assertEqual(self.clients[1].get(f"/api/v1/papers/{job.import_id}/file").status_code, 404)

    def test_successful_reset_preserves_schema_and_unrelated_storage(self):
        paper = self.upload()
        unrelated = self.root / "keep.txt"
        unrelated.write_text("keep")
        for client in self.clients:
            client.__exit__(None, None, None)
        self.clients = []
        self.engine.dispose()
        result = reset(self.settings, database=make_url(TEST_URL).database, storage=self.root, execute=True)
        self.assertTrue(result["executed"])
        self.assertEqual(result["files"], 1)
        self.assertFalse((self.root / "uploads" / f"{paper}.pdf").exists())
        self.assertTrue(unrelated.exists())
        from app.sources.access import acquire_source_permit, release_source_permit
        permit = acquire_source_permit(self.sessions, "arxiv")
        self.assertIsNotNone(permit, "Reset must restore the shared source gate seed")
        release_source_permit(self.sessions, permit)
        with self.engine.connect() as connection:
            from alembic.script import ScriptDirectory
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            self.assertEqual(connection.scalar(text("SELECT version_num FROM alembic_version")),
                ScriptDirectory.from_config(config).get_current_head())
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM users")), 0)
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM papers")), 0)

    def test_import_completion_does_not_deadlock_with_retry_quota_lock(self):
        import hashlib
        from threading import Event
        from sqlalchemy import event
        from sqlalchemy.exc import SQLAlchemyError
        from app.errors import APIError
        submit_import(self.sessions, "arxiv", "1706.03762v1", user_id=self.users[0], settings=self.settings)
        job = claim_import(self.sessions, uuid4())
        staged = staging_path(self.root, job)
        staged.parent.mkdir(parents=True, exist_ok=True)
        data = b"%PDF-lock-fixture"
        staged.write_bytes(data)
        receipt = DownloadReceipt(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        source = self.arxiv_fixture().search.return_value.items[0]
        paper_insert, quota_locked = Event(), Event()
        def before_execute(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO papers "):
                paper_insert.set()
                if not quota_locked.wait(timeout=5):
                    raise TimeoutError("Retry did not acquire its quota lock")
        def after_execute(connection, cursor, statement, parameters, context, executemany):
            if "FROM users" in statement and "FOR " in statement:
                quota_locked.set()
        def complete():
            try:
                return complete_import(self.sessions, job, source, receipt, root=self.root)
            except SQLAlchemyError:
                return "database-lock-failure"
        def retry():
            try:
                retry_import(self.sessions, job.import_id, 1, user_id=self.users[0], settings=self.settings)
                return 200
            except APIError as error:
                return error.status_code
            except SQLAlchemyError:
                return "database-lock-failure"
        event.listen(self.engine, "before_cursor_execute", before_execute)
        event.listen(self.engine, "after_cursor_execute", after_execute)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                completion = pool.submit(complete)
                self.assertTrue(paper_insert.wait(timeout=5))
                retried = pool.submit(retry)
                self.assertIs(completion.result(timeout=10), True)
                self.assertEqual(retried.result(timeout=10), 409)
        finally:
            event.remove(self.engine, "before_cursor_execute", before_execute)
            event.remove(self.engine, "after_cursor_execute", after_execute)

    def test_reset_guards_leave_files_and_schema_intact(self):
        paper = self.upload()
        with self.assertRaises(ValueError):
            reset(self.settings, database="wrong", storage=self.root, execute=True)
        self.assertTrue((self.root / "uploads" / f"{paper}.pdf").exists())
        with self.assertRaises(ValueError):
            reset(self.settings, database=make_url(TEST_URL).database, storage=self.root, execute=True)
        self.assertEqual(self.clients[0].get("/api/v1/papers").json()["total"], 1)


def run_postgres_tests():
    settings = Settings()
    base = make_url(settings.database_url.get_secret_value())
    if base.host != "127.0.0.1":
        raise RuntimeError("Native tests require a loopback PostgreSQL server")
    database = "ownership_tests_" + uuid4().hex
    target = base.set(database=database)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created = False
    try:
        with admin.connect() as connection:
            version = connection.scalar(text("SELECT version()"))
            if "PGlite" in version:
                raise RuntimeError("Native PostgreSQL required")
            connection.exec_driver_sql('CREATE DATABASE "' + database + '"')
            created = True
        environment = dict(os.environ, OWNERSHIP_TEST_DATABASE_URL=target.render_as_string(hide_password=False))
        return subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "-v"], env=environment, timeout=120).returncode
    finally:
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql('DROP DATABASE "' + database + '" WITH (FORCE)')
        admin.dispose()


if __name__ == "__main__":
    if sys.argv[1:] == ["--postgres"]:
        raise SystemExit(run_postgres_tests())
    unittest.main()
