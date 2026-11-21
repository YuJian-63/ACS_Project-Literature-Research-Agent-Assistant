"""Search a user's paper library and read its verified PDFs."""

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, Self
from uuid import UUID

import httpx

from apis.papers import parse_pdf
from config import load_env

# Match the backend's upload limit for sources without a recorded size.
MAX_LIBRARY_PDF_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class LibraryClient:
    base_url: str
    token: str = field(repr=False)

    @classmethod
    def from_env(cls) -> Self | None:
        load_env()
        token = os.getenv("AGENT_LIBRARY_TOKEN", "").strip()
        if not token:
            return None
        base_url = os.getenv("AGENT_LIBRARY_BASE_URL", "").strip() or "http://127.0.0.1:8000"
        return cls(base_url, token)


def search_library(
    base_url: str,
    token: str,
    query: str | None = None,
    *,
    match: Literal["all", "any"] = "all",
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    timeout: float = 30,
) -> dict:
    """Return one backend page (items, total, limit, offset). Omit query to list papers."""
    params = {"match": match, "limit": limit, "offset": offset}
    if query is not None:
        params["q"] = query
    if status is not None:
        params["status"] = status
    response = httpx.get(
        f"{base_url.rstrip('/')}/api/v1/agent/papers",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def download_pdf(
    base_url: str, token: str, paper: dict, destination: Path, *, timeout: float = 120
) -> Path:
    """Download a search result to destination, replacing it only after size and SHA-256 match."""
    path = f"/api/v1/agent/papers/{UUID(paper['id'])}/pdf"
    if paper["download_url"] != path:
        raise ValueError("Download URL does not match the library paper ID")
    size = paper["size_bytes"]
    if type(size) is not int or size < 0:
        raise ValueError("Invalid recorded PDF size")
    return _download_verified(base_url, token, path, destination, paper["sha256"], size, timeout)


def _download_verified(
    base_url: str,
    token: str,
    path: str,
    destination: Path,
    sha256: str,
    expected_size: int | None,
    timeout: float,
) -> Path:
    limit = expected_size if expected_size is not None else MAX_LIBRARY_PDF_BYTES
    with httpx.stream(
        "GET",
        f"{base_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=destination.parent) as directory:
            temporary = Path(directory) / "paper.pdf"
            digest = hashlib.sha256()
            size = 0
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("Download exceeds the PDF size limit")
                    digest.update(chunk)
                    output.write(chunk)
            if (
                expected_size is not None and size != expected_size
            ) or digest.hexdigest() != sha256:
                raise ValueError("Downloaded PDF does not match its recorded size or SHA-256")
            temporary.replace(destination)
    return destination


def read_library_paper(
    client: LibraryClient, source: str, item: dict | None, *, timeout: float = 120
) -> dict:
    """Read a searched or explicitly selected library source under the current user's grant."""
    paper_id, sha256 = source.removeprefix("local:").split("@")
    with TemporaryDirectory() as directory:
        destination = Path(directory) / "paper.pdf"
        if item is None:
            path = f"/api/v1/agent/papers/{UUID(paper_id)}/pdf"
            _download_verified(
                client.base_url, client.token, path, destination, sha256, None, timeout
            )
        else:
            if source != f"local:{item['id']}@{item['sha256']}":
                raise ValueError("Library paper does not match the requested source")
            download_pdf(client.base_url, client.token, item, destination, timeout=timeout)
        paper = parse_pdf(destination, source, title=item["title"] if item else None)
        paper.pop("pdf_path", None)
    return paper
