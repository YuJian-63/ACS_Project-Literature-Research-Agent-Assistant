"""Download arXiv PDFs with httpx and extract page-addressable evidence."""

import argparse
import hashlib
import json
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import pymupdf

from config import DATA_DIR

ARXIV_HOSTS = {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}
ARXIV_ID = re.compile(
    r"(?P<base>(?:\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}|[A-Za-z][A-Za-z.-]*/\d{2}(?:0[1-9]|1[0-2])\d{3}))"
    r"(?P<version>v[1-9]\d*)?"
)
MAX_PDF_BYTES = 25 * 1024 * 1024
CHUNK_CHARS = 3000


def normalize_arxiv_id(source: str) -> str:
    """Accept a bare identifier, arXiv: identifier, or arxiv.org abs/pdf/html URL."""
    value = source.strip()
    if value.lower().startswith("arxiv:"):
        value = value[6:].strip()
    if "://" in value:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in ARXIV_HOSTS
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
        ):
            raise ValueError("Only arxiv.org paper URLs are supported")
        path = unquote(parsed.path).rstrip("/")
        parts = path.split("/", 2)
        if len(parts) != 3 or parts[1] not in {"abs", "pdf", "html"}:
            raise ValueError("Expected an arXiv abs, pdf, or html URL")
        value = parts[2]
    value = value.removesuffix(".pdf")
    if not ARXIV_ID.fullmatch(value):
        raise ValueError("Invalid arXiv identifier")
    return value


def _download_pdf(
    url: str,
    path: Path,
    max_bytes: int = MAX_PDF_BYTES,
    timeout: float = 120,
) -> None:
    """Follow arXiv redirects and publish the cache file only after a complete download."""
    started = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(min(45, timeout), connect=min(15, timeout))) as client:
        for _ in range(6):
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("PDF download exceeded the time limit")
            with client.stream(
                "GET",
                url,
                timeout=min(45, remaining),
                headers={"User-Agent": "LiteratureResearchAgent/0.1"},
            ) as response:
                if response.is_redirect:
                    target = response.url.join(response.headers["location"])
                    if target.scheme != "https" or target.host not in ARXIV_HOSTS:
                        raise ValueError("PDF redirected outside arXiv")
                    url = str(target)
                    continue
                response.raise_for_status()
                size = response.headers.get("content-length")
                if size and int(size) > max_bytes:
                    raise ValueError("PDF exceeds the download size limit")
                content = bytearray()
                for block in response.iter_bytes():
                    content.extend(block)
                    if len(content) > max_bytes:
                        raise ValueError("PDF exceeds the download size limit")
                    if time.monotonic() - started > timeout:
                        raise TimeoutError("PDF download exceeded the time limit")
                if not content.startswith(b"%PDF-"):
                    raise ValueError("arXiv returned non-PDF content")
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=path.parent, suffix=".pdf", delete=False
                ) as handle:
                    temporary = Path(handle.name)
                    try:
                        handle.write(content)
                        handle.flush()
                        temporary.replace(path)
                    finally:
                        temporary.unlink(missing_ok=True)
                return
    raise ValueError("Too many arXiv redirects")


def _split_page(text: str, chunk_chars: int = CHUNK_CHARS) -> list[str]:
    """Keep each chunk as a verbatim slice of its source page."""
    chunks = []
    offset = 0
    while offset < len(text):
        end = min(offset + chunk_chars, len(text))
        if end < len(text):
            boundary = text.rfind("\n", offset + chunk_chars // 2, end)
            if boundary != -1:
                end = boundary + 1
        chunks.append(text[offset:end])
        offset = end
    return chunks


def parse_pdf(path: Path, arxiv_id: str) -> dict:
    """Extract text and stable citations from an already downloaded PDF."""
    arxiv_id = normalize_arxiv_id(arxiv_id)
    match = ARXIV_ID.fullmatch(arxiv_id)
    assert match is not None
    base = match["base"]
    version = match["version"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pymupdf.open(path) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDF is unsupported")
        pages = [{"page": page.number + 1, "text": page.get_text(sort=True)} for page in document]
        title = (document.metadata.get("title") or "").strip() or f"arXiv:{arxiv_id}"
        outline = [
            {"title": heading, "level": level, "page_start": page}
            for level, heading, page in document.get_toc()
            if 1 <= page <= len(pages)
        ]
    if not any(page["text"].strip() for page in pages):
        raise ValueError("PDF has no extractable text")
    watermark = re.search(r"arXiv:\s*" + re.escape(base) + r"(v[1-9]\d*)\b", pages[0]["text"])
    if watermark:
        if version and version != watermark[1]:
            raise ValueError("PDF version does not match the requested arXiv version")
        version = watermark[1]
    paper_id = f"arxiv:{base}"
    source_id = f"{paper_id}{version}" if version else f"{paper_id}@{digest[:12]}"
    resolved_id = base + (version or "")
    chunks = [
        {
            "source_id": source_id,
            "paper_id": paper_id,
            "version": version,
            "chunk_id": f"{source_id}:p{page['page']}:c{number}",
            "page": page["page"],
            "source_text": text,
        }
        for page in pages
        for number, text in enumerate(_split_page(page["text"]), start=1)
        if text.strip()
    ]
    return {
        "paper_id": paper_id,
        "source_id": source_id,
        "title": title,
        "url": f"https://arxiv.org/abs/{resolved_id}",
        "pdf_url": f"https://arxiv.org/pdf/{resolved_id}",
        "version": version,
        "sha256": digest,
        "pdf_path": str(path.resolve()),
        "downloaded_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        "outline": outline,
        "pages": pages,
        "chunks": chunks,
    }


def read_paper(
    source: str,
    cache_dir: Path | None = None,
    *,
    refresh: bool = False,
    timeout: float = 120,
) -> dict:
    """Fetch/cache an arXiv paper and return its metadata, pages, and raw evidence chunks."""
    arxiv_id = normalize_arxiv_id(source)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    directory = Path(cache_dir) if cache_dir is not None else DATA_DIR / "papers"
    path = directory / f"{arxiv_id.replace('/', '_')}.pdf"
    if refresh or not path.exists():
        _download_pdf(f"https://arxiv.org/pdf/{arxiv_id}", path, timeout=timeout)
    return parse_pdf(path, arxiv_id)


def select_chunks(
    paper: dict,
    page_start: int | None = None,
    page_end: int | None = None,
    chunk_ids: list[str] | None = None,
) -> list[dict]:
    """Select original evidence by inclusive, one-based page range or exact chunk IDs."""
    count = len(paper["pages"])
    start = 1 if page_start is None else page_start
    end = count if page_end is None else page_end
    if not 1 <= start <= end <= count:
        raise ValueError(f"Page range must be within 1–{count}")
    known_ids = {chunk["chunk_id"] for chunk in paper["chunks"]}
    if chunk_ids is not None and set(chunk_ids) - known_ids:
        raise ValueError("Unknown evidence chunk ID")
    wanted = None if chunk_ids is None else set(chunk_ids)
    return [
        chunk
        for chunk in paper["chunks"]
        if start <= chunk["page"] <= end and (wanted is None or chunk["chunk_id"] in wanted)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="arXiv ID or URL")
    parser.add_argument("--page-start", type=int)
    parser.add_argument("--page-end", type=int)
    parser.add_argument("--chunk-ids", nargs="+")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    paper = read_paper(args.source, refresh=args.refresh)
    if args.page_start is not None or args.page_end is not None or args.chunk_ids is not None:
        selected = select_chunks(paper, args.page_start, args.page_end, args.chunk_ids)
        paper = {
            **paper,
            "pages": [
                page for page in paper["pages"] if page["page"] in {c["page"] for c in selected}
            ],
            "chunks": selected,
        }
    print(json.dumps(paper, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
