"""Bailian's OpenAI-compatible dense embedding endpoint."""

import hashlib
import math
import os

import httpx

from config import load_env, require_env

BATCH_SIZE = 10
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _base_url() -> str:
    url = os.getenv("EMBEDDING_BASE_URL")
    if not url and os.getenv("MODEL_PROVIDER", "bailian") == "bailian":
        url = os.getenv("MODEL_BASE_URL")
    return (url or DEFAULT_BASE_URL).rstrip("/")


def embedding_settings() -> tuple[str, str]:
    """Identify compatible indexes without using credentials or contacting the service."""
    load_env()
    model = os.getenv("EMBEDDING_MODEL") or "text-embedding-v4"
    dimensions = os.getenv("EMBEDDING_DIMENSIONS") or "1024"
    endpoint_hash = hashlib.sha256(_base_url().encode()).hexdigest()
    return model, f"openai-dense-v1:{endpoint_hash}:{dimensions}"


def embed_texts(
    texts: list[str], *, model: str, timeout: float, purpose: str
) -> tuple[list[list[float]], int | None]:
    """Embed one batch in input order. The caller records document/query usage separately."""
    if not 1 <= len(texts) <= BATCH_SIZE:
        raise ValueError(f"Embedding batch size must be between 1 and {BATCH_SIZE}")
    if purpose not in {"document", "query"}:
        raise ValueError("Unknown embedding purpose")
    key = require_env("BAILIAN_API_KEY")
    try:
        dimensions = int(os.getenv("EMBEDDING_DIMENSIONS") or "1024")
        if dimensions <= 0:
            raise ValueError
    except ValueError:
        raise ValueError("EMBEDDING_DIMENSIONS must be a positive integer") from None
    # The OpenAI-compatible route accepts the same fields for queries and documents.
    try:
        response = httpx.post(
            _base_url() + "/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "input": texts,
                "dimensions": dimensions,
                "encoding_format": "float",
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Embedding request failed (HTTP {exc.response.status_code})") from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise RuntimeError("Embedding request failed") from None

    try:
        payload = response.json()
        rows = sorted(payload["data"], key=lambda row: row["index"])
        if len(rows) != len(texts):
            raise ValueError
        vectors = []
        for index, row in enumerate(rows):
            vector = row["embedding"]
            if (
                type(row["index"]) is not int
                or row["index"] != index
                or not isinstance(vector, list)
                or len(vector) != dimensions
                or not all(type(v) in (float, int) and math.isfinite(v) for v in vector)
            ):
                raise ValueError
            vectors.append(vector)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("Invalid embedding response") from None
    usage = payload.get("usage")
    tokens = (
        usage.get("prompt_tokens", usage.get("total_tokens")) if isinstance(usage, dict) else None
    )
    return vectors, tokens if type(tokens) is int and tokens >= 0 else None
