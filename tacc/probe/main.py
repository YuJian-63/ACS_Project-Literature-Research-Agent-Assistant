"""Small, independent API checks run from a TACC CPU job."""

import argparse
import json
import math
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


class CheckFailed(Exception):
    """A readable check failure, with no provider response or credentials."""


def required(settings: dict, name: str) -> str:
    value = settings.get(name, "").strip()
    if not value:
        raise CheckFailed(f"Missing {name}")
    return value


def post_json(url: str, key: str, payload: dict) -> dict:
    with httpx.Client(timeout=httpx.Timeout(90, connect=15)) as client:
        response = client.post(url, headers={"Authorization": f"Bearer {key}"}, json=payload)
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict):
        raise CheckFailed("Expected a JSON object")
    return result


def model_check(settings: dict, details: dict) -> None:
    base_url = required(settings, "MODEL_BASE_URL").rstrip("/")
    key = required(settings, "BAILIAN_API_KEY")
    model = settings.get("MODEL_NAME", "qwen3.8-27b")
    defaults = {"model": model, "max_tokens": 128, "temperature": 0, "enable_thinking": False}
    details.update(model=model, usage=[])

    def chat(messages: list, **extra) -> dict:
        result = post_json(base_url + "/chat/completions", key, {**defaults, "messages": messages, **extra})
        details["usage"].append(result.get("usage"))
        return result["choices"][0]["message"]

    plain = chat([{"role": "user", "content": "Reply briefly: what is 2 + 3?"}])
    if not (plain.get("content") or "").strip():
        raise CheckFailed("Chat returned no text")
    details["chat_answer"] = plain["content"][:500]

    tool = {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two integers.",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
    }
    messages = [{"role": "user", "content": "Call add with a=7 and b=11. Then state the result."}]
    first = chat(messages, tools=[tool])
    calls = first.get("tool_calls", [])
    if len(calls) != 1:
        raise CheckFailed("Expected one native tool call")
    call = calls[0]
    arguments = json.loads(call["function"]["arguments"])
    if call["function"]["name"] != "add" or arguments != {"a": 7, "b": 11}:
        raise CheckFailed("Unexpected tool name or arguments")
    value = arguments["a"] + arguments["b"]
    details.update(tool_name="add", tool_arguments=arguments, tool_result=value)
    final = chat([
        *messages,
        {"role": "assistant", "content": first.get("content"), "tool_calls": calls},
        {"role": "tool", "tool_call_id": call["id"], "content": str(value)},
    ])
    if final.get("tool_calls") or not (final.get("content") or "").strip():
        raise CheckFailed("Tool round trip returned no final text")
    details["final_answer"] = final["content"][:500]


def search_check(settings: dict, details: dict) -> None:
    query = "Attention Is All You Need transformer"
    result = post_json("https://api.tavily.com/search", required(settings, "TAVILY_API_KEY"), {
        "query": query,
        "topic": "general",
        "search_depth": "basic",
        "max_results": 3,
        "include_domains": ["arxiv.org"],
        "include_answer": False,
        "include_raw_content": False,
    })
    found = result.get("results", [])
    details.update(query=query, result_count=len(found))
    if not found:
        raise CheckFailed("Search returned no results")
    details["results"] = []
    for item in found:
        host = urlparse(item.get("url", "")).hostname or ""
        if host != "arxiv.org" and not host.endswith(".arxiv.org"):
            raise CheckFailed("Search result is outside arXiv")
        if not item.get("title") or not item.get("content", "").strip():
            raise CheckFailed("Search result has no title or snippet")
        details["results"].append({
            "title": item["title"], "url": item["url"], "snippet": item["content"][:400],
        })


def paper_check(settings: dict, details: dict) -> None:
    import pymupdf

    paper_id = "1706.03762v7"
    url = f"https://arxiv.org/pdf/{paper_id}"
    content = bytearray()
    with httpx.Client(timeout=httpx.Timeout(90, connect=15), follow_redirects=True) as client:
        with client.stream("GET", url, headers={"User-Agent": "LiteratureResearchAgent-Probe/0.1"}) as response:
            response.raise_for_status()
            details.update(paper_id=paper_id, url=str(response.url), http_status=response.status_code)
            for block in response.iter_bytes():
                content.extend(block)
                if len(content) > 25 * 1024 * 1024:
                    raise CheckFailed("PDF exceeds 25 MiB")
    if not content.startswith(b"%PDF-"):
        raise CheckFailed("Download is not a PDF")
    with pymupdf.open(stream=content, filetype="pdf") as document:
        texts = [page.get_text(sort=True) for page in document]
        details.update(bytes=len(content), pages=len(document), text_characters=sum(map(len, texts)))
        if not any(text.strip() for text in texts):
            raise CheckFailed("PDF has no extractable text")
        details["excerpt"] = next(text.strip()[:500] for text in texts if text.strip())


def database_check(settings: dict, details: dict) -> None:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.types.json import Jsonb

    options = conninfo_to_dict(required(settings, "DATABASE_URL"))
    options.setdefault("sslmode", "require")
    options["connect_timeout"] = "15"
    options["options"] = "-c statement_timeout=15000"
    payload = {"message": "TACC 连接测试", "value": 42}
    with psycopg.connect(**options) as connection:
        details.update(server_version=connection.info.server_version, tls=connection.pgconn.ssl_in_use)
        connection.execute("CREATE TEMP TABLE api_probe (payload jsonb) ON COMMIT DROP")
        connection.execute("INSERT INTO api_probe VALUES (%s)", (Jsonb(payload),))
        actual = connection.execute("SELECT payload FROM api_probe").fetchone()[0]
        if actual != payload:
            raise CheckFailed("JSONB write/read did not match")
        details["jsonb_roundtrip"] = True


def embedding_check(settings: dict, details: dict) -> None:
    model = settings.get("EMBEDDING_MODEL", "text-embedding-v4")
    dimensions = int(settings.get("EMBEDDING_DIMENSIONS", "1024"))
    base_url = settings.get("EMBEDDING_BASE_URL") or required(settings, "MODEL_BASE_URL")
    inputs = ["Transformers use attention to model sequences.", "检索相关论文片段。"]
    result = post_json(base_url.rstrip("/") + "/embeddings", required(settings, "BAILIAN_API_KEY"), {
        "model": model, "input": inputs, "dimensions": dimensions, "encoding_format": "float",
    })
    details.update(model=model, dimensions=dimensions, usage=result.get("usage"))
    vectors = result.get("data", [])
    if len(vectors) != len(inputs) or sorted(row["index"] for row in vectors) != list(range(len(inputs))):
        raise CheckFailed("Embedding count or indices do not match inputs")
    details["vectors"] = []
    for row in sorted(vectors, key=lambda row: row["index"]):
        vector = row["embedding"]
        if len(vector) != dimensions or not all(type(v) in (int, float) and math.isfinite(v) for v in vector):
            raise CheckFailed("Invalid embedding dimensions or values")
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            raise CheckFailed("Embedding is a zero vector")
        details["vectors"].append({"index": row["index"], "dimensions": len(vector), "norm": round(norm, 6)})


def backend_check(settings: dict, details: dict) -> None:
    import pymupdf

    base_url = required(settings, "BACKEND_BASE_URL").rstrip("/")
    query = "attention 注意力"
    expected = [{
        "id": "probe-paper",
        "title": "TACC backend probe",
        "pdf_url": "/paper.pdf",
        "snippet": "Static fixture for testing HTTP access.",
    }]
    with httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(90, connect=15),
        follow_redirects=True,
        headers={"User-Agent": "LiteratureResearchAgent-Probe/0.1"},
    ) as client:
        response = client.get("/health")
        response.raise_for_status()
        health = response.json()
        if not isinstance(health, dict) or health.get("ok") is not True or health.get("service") != "lr-backend-probe":
            raise CheckFailed("Backend health response did not match")
        details["health"] = {"ok": True, "service": health["service"]}

        response = client.post("/search", json={"query": query})
        response.raise_for_status()
        search = response.json()
        if not isinstance(search, dict) or search.get("query") != query or search.get("results") != expected:
            raise CheckFailed("Backend search response did not match")
        details.update(query=query, results=search["results"])

        response = client.get(search["results"][0]["pdf_url"])
        response.raise_for_status()
        content = response.content
        if not content.startswith(b"%PDF-"):
            raise CheckFailed("Backend download is not a PDF")
        with pymupdf.open(stream=content, filetype="pdf") as document:
            text = "\n".join(page.get_text(sort=True) for page in document)
            details.update(bytes=len(content), pages=len(document), excerpt=text.strip()[:500])
            if len(document) != 1 or "TACC backend probe" not in text:
                raise CheckFailed("Backend PDF content did not match")


DEFAULT_CHECKS = ("model", "search", "paper", "database", "embedding")
CHECKS = {
    "model": model_check,
    "search": search_check,
    "paper": paper_check,
    "database": database_check,
    "embedding": embedding_check,
    "backend": backend_check,
}


def error_details(error: Exception) -> dict:
    # HTTP and database exception strings may expose credentials; do not serialize them.
    result = {"type": type(error).__name__}
    if isinstance(error, CheckFailed):
        result["message"] = str(error)
    elif isinstance(error, httpx.HTTPStatusError):
        result["http_status"] = error.response.status_code
    elif getattr(error, "sqlstate", None):
        result["sqlstate"] = error.sqlstate
    return result


def save_report(output: Path, report: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "runs" / "probe-local.json")
    parser.add_argument("--only", nargs="+", choices=CHECKS, help="Run selected checks")
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    settings = dict(os.environ)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "job_id": os.getenv("SLURM_JOB_ID"),
        "hostname": platform.node(),
        "python": platform.python_version(),
        "status": "running",
        "checks": [],
    }
    save_report(args.output, report)
    for name in args.only or DEFAULT_CHECKS:
        print(f"RUN {name}", flush=True)
        started = time.monotonic()
        item = {"name": name, "status": "pass", "details": {}}
        try:
            CHECKS[name](settings, item["details"])
        except Exception as error:
            item.update(status="fail", error=error_details(error))
        item["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["checks"].append(item)
        save_report(args.output, report)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    passed = sum(item["status"] == "pass" for item in report["checks"])
    report.update(status="pass" if passed == len(report["checks"]) else "fail", passed=passed)
    save_report(args.output, report)
    print(f"{report['status'].upper()}: {passed}/{len(report['checks'])}; report={args.output}", flush=True)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
