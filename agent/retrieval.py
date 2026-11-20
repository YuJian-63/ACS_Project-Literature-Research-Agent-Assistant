"""Lazily index each selected paper and rank their original chunks together."""

import hashlib
import json
import math
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from apis.embeddings import BATCH_SIZE
from baseline import RunLog, RunStopped, check_time, request_timeout


def _unit_vectors(
    rows: list, count: int, dimensions: int | None, *, cached: bool = False
) -> list[list[float]]:
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("Embedding count does not match the number of inputs")
    normalized = []
    for row in rows:
        if (
            not isinstance(row, list)
            or not row
            or (dimensions is not None and len(row) != dimensions)
        ):
            raise ValueError("Embedding dimensions do not match")
        if not all(type(n) in (int, float) and math.isfinite(n) for n in row):
            raise ValueError("Embedding contains invalid values")
        length = math.hypot(*row)
        if not length or not math.isfinite(length):
            raise ValueError("Embedding has invalid length")
        dimensions = len(row)
        if cached:
            if not math.isclose(length, 1.0):
                raise ValueError("Cached embedding is not a unit vector")
            normalized.append(row)
        else:
            normalized.append([n / length for n in row])
    return normalized


def _embed_batch(
    texts: list[str],
    embed: Callable,
    model: str,
    purpose: str,
    dimensions: int | None,
    source_ids: list[str],
    log: RunLog,
) -> list[list[float]]:
    timeout = request_timeout(log, 60)
    started = time.monotonic()
    entry = {
        "kind": "embedding",
        "purpose": purpose,
        "model": model,
        "input_count": len(texts),
        "input_tokens": None,
    }
    if len(source_ids) == 1:
        entry["source_id"] = source_ids[0]
    else:
        entry["source_ids"] = source_ids
    try:
        rows, tokens = embed(texts, model=model, timeout=timeout, purpose=purpose)
        if type(tokens) is int and tokens >= 0:
            entry["input_tokens"] = tokens
        return _unit_vectors(rows, len(texts), dimensions)
    except RunStopped:
        raise
    except Exception as exc:  # noqa: BLE001 - provider errors can contain credentials or input
        entry["error"] = type(exc).__name__
        raise ValueError(f"Embedding {purpose} request failed") from None
    finally:
        entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
        log.trace.append(entry)
        check_time(log)


def _paper_vectors(
    paper: dict,
    *,
    embed: Callable,
    embedding_model: str,
    embedding_namespace: str,
    cache_dir: Path,
    log: RunLog,
    dimensions: int | None,
) -> list[list[float]]:
    check_time(log)
    chunks = paper["chunks"]
    if not chunks:
        raise ValueError("This paper has no searchable chunks")
    source_id = paper["source_id"]
    started = time.monotonic()
    # Include exact text and order so a different parser or chunk layout gets a new index.
    identity = [
        "paper-index-v1",
        embedding_namespace,
        embedding_model,
        source_id,
        paper.get("sha256"),
        [(chunk["chunk_id"], chunk["source_text"]) for chunk in chunks],
    ]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    path = cache_dir / f"{digest}.json"
    try:
        with path.open() as f:
            vectors = _unit_vectors(json.load(f), len(chunks), dimensions, cached=True)
        action = "reuse"
    except (FileNotFoundError, ValueError, OverflowError):
        action = "build"
        vectors = []
        cache_dir.mkdir(parents=True, exist_ok=True)
        for offset in range(0, len(chunks), BATCH_SIZE):
            texts = [chunk["source_text"] for chunk in chunks[offset : offset + BATCH_SIZE]]
            batch = _embed_batch(
                texts, embed, embedding_model, "document", dimensions, [source_id], log
            )
            dimensions = len(batch[0])
            vectors.extend(batch)
        # Publish the whole index in one rename; concurrent readers only see complete files.
        with tempfile.NamedTemporaryFile(mode="w", dir=cache_dir, delete_on_close=False) as f:
            json.dump(vectors, f, separators=(",", ":"))
            f.close()
            check_time(log)
            Path(f.name).replace(path)
    log.trace.append(
        {
            "kind": "retrieval_index",
            "action": action,
            "source_id": source_id,
            "model": embedding_model,
            "index_id": digest,
            "dimensions": len(vectors[0]),
            "chunks": len(chunks),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    )
    return vectors


def rank_chunks(
    paper: dict | list[dict],
    query: str,
    *,
    top_k: int,
    embed: Callable,
    embedding_model: str,
    cache_dir: Path,
    log: RunLog,
    embedding_namespace: str = "",
) -> list[dict]:
    """Return the global top_k. Ties retain selected-paper order, then chunk order."""
    papers = [paper] if isinstance(paper, dict) else paper
    if not papers or not query.strip() or top_k < 1:
        raise ValueError("Retrieval requires papers, a query and a positive top_k")
    source_ids = [selected["source_id"] for selected in papers]
    query_vector = None
    hits = []
    for selected in papers:
        vectors = _paper_vectors(
            selected,
            embed=embed,
            embedding_model=embedding_model,
            embedding_namespace=embedding_namespace,
            cache_dir=cache_dir,
            log=log,
            dimensions=len(query_vector) if query_vector is not None else None,
        )
        if query_vector is None:
            [query_vector] = _embed_batch(
                [query], embed, embedding_model, "query", len(vectors[0]), source_ids, log
            )
        for chunk, vector in zip(selected["chunks"], vectors, strict=True):
            hits.append((math.sumprod(query_vector, vector), chunk))
    hits.sort(key=lambda hit: hit[0], reverse=True)
    check_time(log)
    return [chunk for score, chunk in hits[:top_k]]
