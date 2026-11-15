"""Explicitly reset this application's rows and generated files, preserving its schema."""
import argparse
import json
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db.models import Base
from app.db.session import create_database_engine


GENERATED_PART = re.compile(r"[0-9a-f-]{36}-(?:[0-9]+-[0-9a-f-]{36}|[A-Za-z0-9_-]+)\.part")


def planned_files(root: Path) -> list[Path]:
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ValueError("Storage root must not be a link")
    root = root.resolve(strict=True)
    files = []
    for directory in ("uploads", "import-temp"):
        target = root / directory
        if not target.exists():
            continue
        if target.resolve() != target or target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
            raise ValueError("Generated directory must not be a link")
        for item in target.iterdir():
            if not item.is_file() or item.is_symlink() or item.resolve() != item:
                raise ValueError("Unexpected generated storage entry")
            if item.suffix == ".pdf" and directory == "uploads":
                if str(UUID(item.stem)) != item.stem:
                    raise ValueError("Unexpected PDF filename")
            elif not GENERATED_PART.fullmatch(item.name):
                raise ValueError("Unexpected generated filename")
            files.append(item)
    return files


def reset(settings: Settings, *, database: str, storage: Path, execute: bool = False) -> dict:
    configured = make_url(settings.database_url.get_secret_value())
    root = settings.storage_root
    if database != configured.database or storage.absolute() != root:
        raise ValueError("Explicit database/storage confirmation must match settings")
    engine = create_database_engine(settings)
    try:
        with engine.begin() as connection:
            actual = connection.scalar(text("SELECT current_database()"))
            if actual != database:
                raise ValueError("Connected database does not match confirmation")
            tables = set(inspect(connection).get_table_names(schema="public")) & set(Base.metadata.tables)
            if not {"papers", "tasks", "alembic_version"}.issubset(tables | ({"alembic_version"} if inspect(connection).has_table("alembic_version") else set())):
                raise ValueError("Expected application schema is missing")
            others = connection.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'"))
            if execute and others:
                raise ValueError("Stop all API and worker database connections before reset")
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            names = ", ".join('"' + table + '"' for table in sorted(tables))
            if execute:
                connection.execute(text("LOCK TABLE " + names + " IN ACCESS EXCLUSIVE MODE"))
            files = planned_files(root)
            counts = {table: connection.scalar(text('SELECT count(*) FROM "' + table + '"')) for table in sorted(tables)}
            result = {"database": actual, "storage": str(root), "rows": counts, "files": len(files), "executed": execute}
            if execute:
                connection.execute(text("TRUNCATE TABLE " + names))
                if "source_request_gates" in tables:
                    connection.execute(text("INSERT INTO source_request_gates (provider) VALUES ('arxiv')"))
        if execute:
            for item in files:
                if item.resolve() != item or item.is_symlink():
                    raise ValueError("Generated file changed after preflight")
                item.unlink(missing_ok=True)
        return result
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--storage", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="Delete confirmed application rows/files; default is dry-run")
    arguments = parser.parse_args()
    try:
        result = reset(Settings(), database=arguments.database, storage=arguments.storage, execute=arguments.execute)
    except Exception as error:
        print("Reset aborted: " + (str(error) if isinstance(error, ValueError) else type(error).__name__))
        raise SystemExit(1) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
