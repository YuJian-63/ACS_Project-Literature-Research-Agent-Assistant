"""Neon/PostgreSQL connectivity and JSONB storage for baseline artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from config import require_env


class DatabaseError(RuntimeError):
    """A database operation failed; connection credentials are not included."""


@contextmanager
def _connect() -> Iterator[psycopg.Connection]:
    try:
        options = conninfo_to_dict(require_env("DATABASE_URL"))
        options.setdefault("sslmode", "require")
        options.setdefault("connect_timeout", "15")
        options.setdefault("options", "-c statement_timeout=15000")
        with psycopg.connect(**options) as connection:
            yield connection
    except psycopg.Error as exc:
        raise DatabaseError(
            f"PostgreSQL operation failed: {type(exc).__name__} "
            f"(SQLSTATE {exc.sqlstate or 'unavailable'})."
        ) from None


def _ensure_schema(connection: psycopg.Connection) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS agt_baseline")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS agt_baseline.papers (
            source_id text PRIMARY KEY,
            paper_id text NOT NULL,
            document jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS papers_paper_id_idx ON agt_baseline.papers (paper_id)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS agt_baseline.runs (
            task_id text PRIMARY KEY,
            result jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )"""
    )


def _identifier(document: dict[str, Any], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def probe() -> dict[str, Any]:
    """Verify a connection and JSONB write/read using a transaction-local table."""
    payload = {"message": "Neon 连接测试", "value": 42}
    with _connect() as connection:
        database, user = connection.execute("SELECT current_database(), current_user").fetchone()
        connection.execute(
            "CREATE TEMP TABLE agt_connectivity_probe (payload jsonb) ON COMMIT DROP"
        )
        connection.execute(
            "INSERT INTO agt_connectivity_probe (payload) VALUES (%s)",
            (Jsonb(payload),),
        )
        actual = connection.execute("SELECT payload FROM agt_connectivity_probe").fetchone()[0]
        if actual != payload:
            raise DatabaseError("PostgreSQL JSONB roundtrip did not match.")
        return {
            "ok": True,
            "database": database,
            "user": user,
            "server_version": connection.info.server_version,
            "jsonb_roundtrip": True,
        }


def save_paper(paper: dict[str, Any]) -> None:
    """Save parsed pages and evidence; different source versions stay separate."""
    source_id = _identifier(paper, "source_id")
    paper_id = _identifier(paper, "paper_id")
    with _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            """INSERT INTO agt_baseline.papers (source_id, paper_id, document)
               VALUES (%s, %s, %s)
               ON CONFLICT (source_id) DO UPDATE
               SET paper_id = EXCLUDED.paper_id, document = EXCLUDED.document,
                   updated_at = now()""",
            (source_id, paper_id, Jsonb(paper)),
        )


def load_paper(paper_id: str, source_id: str | None = None) -> dict[str, Any] | None:
    """Read one exact source, or the most recently saved version of a paper."""
    with _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            """SELECT document FROM agt_baseline.papers
               WHERE paper_id = %s AND (%s::text IS NULL OR source_id = %s)
               ORDER BY updated_at DESC, source_id DESC LIMIT 1""",
            (paper_id, source_id, source_id),
        ).fetchone()
        return row[0] if row else None


def save_run(result: dict[str, Any]) -> None:
    """Save a task result, including citations, evidence, usage and trace."""
    task_id = _identifier(result, "task_id")
    with _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            """INSERT INTO agt_baseline.runs (task_id, result) VALUES (%s, %s)
               ON CONFLICT (task_id) DO UPDATE
               SET result = EXCLUDED.result, updated_at = now()""",
            (task_id, Jsonb(result)),
        )


def load_run(task_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT result FROM agt_baseline.runs WHERE task_id = %s", (task_id,)
        ).fetchone()
        return row[0] if row else None


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), ensure_ascii=False, indent=2))
    except (DatabaseError, ValueError) as error:
        raise SystemExit(str(error)) from None
