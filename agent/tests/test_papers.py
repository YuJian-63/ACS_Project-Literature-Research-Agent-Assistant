import asyncio

import httpx
import pymupdf
import pytest

from apis import papers, search_web


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("arXiv:1706.03762v7", "1706.03762v7"),
        ("https://arxiv.org/abs/1706.03762?context=cs#page=2", "1706.03762"),
        ("https://arxiv.org/pdf/hep-th/9901001v2.pdf", "hep-th/9901001v2"),
        ("https://export.arxiv.org/html/0704.0001v1/", "0704.0001v1"),
    ],
)
def test_normalize_arxiv_id(source, expected):
    assert papers.normalize_arxiv_id(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "https://arxiv.org.evil.example/pdf/1706.03762",
        "https://example.org/pdf/1706.03762",
        "https://arxiv.org/search/1706.03762",
        "https://user:password@arxiv.org/pdf/1706.03762",
        "https://arxiv.org/pdf/../../1706.03762",
        "1713.03762",
        "1706.03762v0",
        "not a paper",
    ],
)
def test_reject_invalid_sources(source):
    with pytest.raises(ValueError):
        papers.normalize_arxiv_id(source)


@pytest.fixture
def pdf_path(tmp_path):
    path = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 40), "arXiv:1706.03762v7\nAttention Is All You Need")
        page = doc.new_page()
        page.insert_text((40, 40), "The Transformer uses attention without recurrence.")
        doc.set_metadata({"title": "Attention Is All You Need"})
        doc.save(path)
    return path


def test_parser_preserves_evidence_and_version(pdf_path):
    paper = papers.parse_pdf(pdf_path, "1706.03762")
    assert paper["title"] == "Attention Is All You Need"
    assert paper["paper_id"] == "arxiv:1706.03762"
    assert paper["source_id"] == "arxiv:1706.03762v7"
    assert paper["version"] == "v7"
    assert paper["outline"] == []
    assert [page["page"] for page in paper["pages"]] == [1, 2]
    for page in paper["pages"]:
        chunks = papers.select_chunks(paper, page["page"], page["page"])
        assert "".join(chunk["source_text"] for chunk in chunks) == page["text"]
        assert all(chunk["source_id"] == paper["source_id"] for chunk in chunks)
    chosen = paper["chunks"][-1]
    assert papers.select_chunks(paper, chunk_ids=[chosen["chunk_id"]]) == [chosen]
    with pytest.raises(ValueError):
        papers.select_chunks(paper, 0, 3)
    with pytest.raises(ValueError):
        papers.select_chunks(paper, chunk_ids=["invented"])


def test_parser_reads_pdf_bookmarks_and_skips_missing_destinations(pdf_path, tmp_path):
    path = tmp_path / "bookmarked.pdf"
    with pymupdf.open(pdf_path) as document:
        document.set_toc([[1, "Introduction", 1], [2, "Method", 2], [1, "No page destination", -1]])
        document.save(path)

    paper = papers.parse_pdf(path, "1706.03762")
    assert paper["outline"] == [
        {"title": "Introduction", "level": 1, "page_start": 1},
        {"title": "Method", "level": 2, "page_start": 2},
    ]


def test_chunks_are_bounded_verbatim_slices():
    text = ("A paragraph with an experimental result.\n" * 300) + "last line"
    chunks = papers._split_page(text)
    assert "".join(chunks) == text
    assert max(map(len, chunks)) <= papers.CHUNK_CHARS


def test_mismatched_version_does_not_misattribute_evidence(pdf_path):
    with pytest.raises(ValueError, match="version"):
        papers.parse_pdf(pdf_path, "1706.03762v1")


def test_unknown_version_uses_content_identity(tmp_path):
    path = tmp_path / "unversioned.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 40), "Some original text.")
        doc.save(path)
    paper = papers.parse_pdf(path, "1706.03762")
    assert paper["version"] is None
    assert paper["source_id"] == "arxiv:1706.03762@" + paper["sha256"][:12]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>not a PDF</html>"),
        httpx.Response(200, content=b"%PDF-" + b"x" * 50),
        httpx.Response(302, headers={"location": "https://example.org/paper.pdf"}),
    ],
)
def test_failed_download_does_not_publish_cache(tmp_path, monkeypatch, response):
    client_class = httpx.Client
    monkeypatch.setattr(
        papers.httpx,
        "Client",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(lambda request: response), **kwargs
        ),
    )
    destination = tmp_path / "papers" / "paper.pdf"
    with pytest.raises(ValueError):
        papers._download_pdf("https://arxiv.org/pdf/1706.03762", destination, max_bytes=25)
    assert not destination.exists()


def test_search_deadline_cancels_inflight_request(monkeypatch):
    cancelled = []

    class SlowSearch:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, query):
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.append(True)

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(search_web, "load_env", lambda: None)
    monkeypatch.setattr(search_web, "TavilySearch", SlowSearch)
    with pytest.raises(TimeoutError):
        search_web.search_web("paper", timeout=0.01)
    assert cancelled == [True]


def test_search_errors_redact_api_key(monkeypatch):
    class FailedSearch:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, query):
            return {"error": "invalid credential test-key"}

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(search_web, "load_env", lambda: None)
    monkeypatch.setattr(search_web, "TavilySearch", FailedSearch)
    with pytest.raises(RuntimeError) as error:
        search_web.search_web("paper")
    assert "test-key" not in str(error.value)
    assert "invalid credential" in str(error.value)
