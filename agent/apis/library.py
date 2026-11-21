"""Search a user's paper library and download a verified copy of a search result."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import UUID

import httpx


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
                    if size > paper["size_bytes"]:
                        raise ValueError("Download exceeds the recorded PDF size")
                    digest.update(chunk)
                    output.write(chunk)
            if size != paper["size_bytes"] or digest.hexdigest() != paper["sha256"]:
                raise ValueError("Downloaded PDF does not match its recorded size or SHA-256")
            temporary.replace(destination)
    return destination
