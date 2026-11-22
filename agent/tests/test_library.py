"""Offline Agent QA using a real PDF and the authenticated library HTTP contract."""

import hashlib
import json

import httpx
import pymupdf
import pytest
from test_baseline import ScriptedModel, call, final, message, observations
from test_extension import embed_texts

import baseline
import extension
from apis.library import LibraryClient
from schemas import Task

PAPER_ID = "11111111-1111-4111-8111-111111111111"
TOKEN = "test-library-bearer"
QUOTE = "The library study included 25 participants."
SEARCH_PATH = "/api/v1/agent/papers"
PDF_PATH = f"{SEARCH_PATH}/{PAPER_ID}/pdf"


@pytest.mark.parametrize("saved_credentials", [True, False])
def test_cli_library_login_uses_session_and_csrf(monkeypatch, saved_credentials):
    monkeypatch.setattr("apis.library.load_env", lambda: None)
    monkeypatch.setenv("AGENT_LIBRARY_BASE_URL", "https://api.test")
    monkeypatch.setenv("AGENT_LIBRARY_ORIGIN", "https://web.test")
    for key, value in [("USERNAME", "reader"), ("PASSWORD", "test password")]:
        monkeypatch.setenv(f"AGENT_LIBRARY_{key}", value if saved_credentials else "")
    if not saved_credentials:
        monkeypatch.setattr("builtins.input", lambda prompt: "reader")
        monkeypatch.setattr("apis.library.getpass", lambda prompt: "test password")

    def serve(request):
        assert request.headers["Origin"] == "https://web.test"
        if request.url.path == "/api/v1/auth/login":
            assert json.loads(request.content) == {"username": "reader", "password": "test password"}
            return httpx.Response(200, headers={"Set-Cookie": "session=test; Path=/; HttpOnly"},
                                  json={"csrf_token": "test-csrf"})
        assert request.url.path == "/api/v1/agent/library-token"
        assert request.headers["Cookie"] == "session=test"
        assert request.headers["X-CSRF-Token"] == "test-csrf"
        return httpx.Response(200, json={"access_token": TOKEN})

    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(serve), **kw))
    assert LibraryClient.login_from_cli() == LibraryClient("https://api.test", TOKEN)


@pytest.fixture
def library_backend(monkeypatch):
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 40), f"arXiv:1706.03762v7\n{QUOTE}")
        document.set_toc([[1, "Study", 1]])
        content = document.tobytes()
    record = {
        "id": PAPER_ID,
        "title": "Library study",
        "original_filename": "study.pdf",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "status": "ready",
        "page_count": 1,
        "download_url": PDF_PATH,
    }
    requests = []

    def serve(request):
        requests.append(request)
        assert request.method == "GET"
        if request.headers["Authorization"] != f"Bearer {TOKEN}":
            return httpx.Response(404)
        if request.url.path == PDF_PATH:
            return httpx.Response(200, content=content, headers={"content-type": "application/pdf"})
        assert request.url.path == SEARCH_PATH
        params = request.url.params
        offset = int(params.get("offset", 0))
        return httpx.Response(
            200,
            json={
                "items": [record],
                "total": offset + 1,
                "limit": int(params["limit"]),
                "offset": offset,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(serve)) as http:
        monkeypatch.setattr(httpx, "get", http.get)
        monkeypatch.setattr(httpx, "stream", http.stream)
        yield LibraryClient("https://library.test", TOKEN), record, requests


@pytest.mark.parametrize("workflow", [baseline, extension], ids=["baseline", "extension"])
def test_library_search_open_and_cite_original_pdf(workflow, library_backend, tmp_path):
    library, record, requests = library_backend
    source = f"local:{PAPER_ID}@{record['sha256']}"
    chunk = f"{source}:p1:c1"
    options = {}
    read = call("read_paper", source=source, page_start=1, page_end=1)
    if workflow is extension:
        read = call("retrieve", source=source, query="participants", top_k=1)
        options = {"index_dir": tmp_path, "embed": embed_texts}
    model = ScriptedModel(
        [
            message(
                calls=[call("search_library", query="study participants", match="any", offset=5)]
            ),
            message(calls=[call("open_paper", source=source)]),
            message(calls=[read]),
            final(chunk),
        ]
    )
    result = workflow.run_task(
        Task(question="How many participants?", allow_search=True, max_papers=1),
        model_factory=model.factory,
        library=library,
        **options,
    )

    assert result.stop_reason == "completed"
    assert [r.url.path for r in requests] == [SEARCH_PATH, PDF_PATH]
    params = requests[0].url.params
    assert (params["q"], params["match"], params["offset"], params["limit"]) == (
        "study participants",
        "any",
        "5",
        "5",
    )
    found, opened, read_result = observations(result)
    assert (found["total"], found["offset"], found["limit"]) == (6, 5, 5)
    assert [(hit["source"], hit["title"]) for hit in found["results"]] == [
        (source, record["title"])
    ]
    assert opened["source_id"] == source
    assert opened["outline"] == [{"title": "Study", "level": 1, "page_start": 1}]
    assert "chunks" not in opened
    assert read_result["chunks"][0]["chunk_id"] == chunk
    [evidence] = result.citations
    assert (evidence.source_id, evidence.chunk_id, evidence.paper_id) == (source, chunk, PAPER_ID)
    assert evidence.version is None
    assert evidence.url == ""
    assert evidence.page == 1 and QUOTE in evidence.source_text
    assert TOKEN not in result.model_dump_json()
    assert TOKEN not in repr(model.inputs)
    tools = {tool.name: tool.tool_call_schema.model_fields for tool in model.bound_tools[0]}
    assert "search_papers" in tools
    assert set(tools["search_library"]) == {"query", "match", "offset"}
    assert set(tools["open_paper"]) == {"source"}


def test_explicit_library_source_requires_current_grant_even_after_a_successful_read(
    library_backend,
):
    library, record, requests = library_backend
    source = f"local:{PAPER_ID}@{record['sha256']}"

    def read_as(client):
        model = ScriptedModel(
            [
                message(calls=[call(source=source, page_start=1, page_end=1)]),
                final(f"{source}:p1:c1"),
            ]
        )
        result = baseline.run_task(
            Task(question="What did the study report?", sources=[source]),
            model_factory=model.factory,
            library=client,
        )
        assert not {"search_library", "search_papers"} & {
            tool.name for tool in model.bound_tools[0]
        }
        return result

    result = read_as(library)
    assert result.stop_reason == "completed"
    denied = read_as(LibraryClient(library.base_url, "other-user-grant"))
    assert "error" in observations(denied)[0]
    assert not denied.sources and not denied.citations
    assert "other-user-grant" not in denied.model_dump_json()
    assert [r.url.path for r in requests] == [PDF_PATH, PDF_PATH]


def test_only_returned_library_version_is_authorized_and_counts_towards_paper_limit(
    library_backend,
):
    library, record, requests = library_backend
    source = f"local:{PAPER_ID}@{record['sha256']}"
    model = ScriptedModel(
        [
            message(calls=[call("search_library", query="study")]),
            message(calls=[call("open_paper", source=f"local:{PAPER_ID}@{'0' * 64}")]),
            message(calls=[call("open_paper", source=source)]),
            message(calls=[call("open_paper", source="1706.03762v7")]),
            final(f"{source}:p1:c1"),
        ]
    )
    result = baseline.run_task(
        Task(question="Q", allow_search=True, sources=["1706.03762v7"], max_papers=1),
        model_factory=model.factory,
        library=library,
        reader=lambda *args, **kwargs: pytest.fail("arXiv reader called after paper limit"),
    )
    found, unlisted, opened, limited = observations(result)
    assert found["results"][0]["source"] == source
    assert "error" in unlisted
    assert opened["source_id"] == source
    assert "limit" in limited["error"].lower()
    assert [r.url.path for r in requests] == [SEARCH_PATH, PDF_PATH]
    # Opening the library PDF alone publishes no evidence.
    assert result.stop_reason == "invalid_citations"
    assert not result.citations


@pytest.mark.parametrize("bad_field", ["sha256", "size_bytes"])
def test_library_download_must_match_search_metadata(library_backend, bad_field):
    library, record, _ = library_backend
    record[bad_field] = "0" * 64 if bad_field == "sha256" else record["size_bytes"] + 1
    source = f"local:{PAPER_ID}@{record['sha256']}"
    model = ScriptedModel(
        [
            message(calls=[call("search_library", query="study")]),
            message(calls=[call(source=source, page_start=1, page_end=1)]),
            final(f"{source}:p1:c1"),
        ]
    )
    result = baseline.run_task(
        Task(question="Q", allow_search=True), model_factory=model.factory, library=library
    )
    assert "error" in observations(result)[1]
    assert result.stop_reason == "invalid_citations"
    assert not result.sources and not result.citations
