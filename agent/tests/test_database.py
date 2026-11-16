"""Live persistence check: AGT_TEST_DATABASE=1 uv run pytest tests/test_database.py."""

import os
from uuid import uuid4

import pytest

from apis import database


@pytest.mark.skipif(
    os.environ.get("AGT_TEST_DATABASE") != "1",
    reason="set AGT_TEST_DATABASE=1 to run against DATABASE_URL",
)
def test_neon_artifacts_roundtrip_and_version_isolation():
    identifier = f"integration-test:{uuid4()}"
    paper = {
        "paper_id": identifier,
        "source_id": f"{identifier}v1",
        "version": "v1",
        "chunks": [{"source_text": "引文 ' \\ ; SELECT 1;"}],
    }
    newer_paper = {**paper, "source_id": f"{identifier}v2", "version": "v2"}
    result = {"task_id": identifier, "answer": "待补充", "citations": []}
    try:
        assert database.probe()["jsonb_roundtrip"] is True
        database.save_paper(paper)
        database.save_paper(newer_paper)
        assert database.load_paper(identifier, paper["source_id"]) == paper
        assert database.load_paper(identifier) == newer_paper
        database.save_run(result)
        result["answer"] = "中文引文与 JSONB 已验证"
        database.save_run(result)
        assert database.load_run(identifier) == result
        assert database.load_paper(f"{identifier}:missing") is None
        assert database.load_run(f"{identifier}:missing") is None
    finally:
        with database._connect() as connection:
            database._ensure_schema(connection)
            connection.execute("DELETE FROM agt_baseline.papers WHERE paper_id = %s", (identifier,))
            connection.execute("DELETE FROM agt_baseline.runs WHERE task_id = %s", (identifier,))
