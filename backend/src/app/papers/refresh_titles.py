import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Paper
from app.db.session import create_database_engine, create_session_factory
from app.papers.pdf_parser import ParseFailure
from app.tasks.lifecycle import database_time
from app.workers.parser import ParserWorker


def refresh_titles(sessions: sessionmaker[Session], settings: Settings, *, execute: bool = False) -> dict[str, int]:
    report = {'candidates': 0, 'titles_found': 0, 'updated': 0, 'failed': 0}
    worker = ParserWorker(sessions, settings)
    cursor = None
    while True:
        conditions = [Paper.status == 'ready', ~Paper.source.has()]
        if cursor is not None:
            conditions.append(Paper.id > cursor)
        with sessions() as session:
            records = session.execute(select(Paper.id, Paper.title, Paper.original_filename, Paper.sha256, Paper.size_bytes)
                .where(*conditions).order_by(Paper.id).limit(100)).all()
        if not records:
            return report
        for record in records:
            cursor = record.id
            if record.title != record.original_filename[:-4].strip():
                continue
            report['candidates'] += 1
            try:
                result = worker.extract(record.id, record.sha256, record.size_bytes, maintain_lease=False)
            except (ParseFailure, OSError, ValueError):
                report['failed'] += 1
                continue
            if not result.title or result.title == record.title:
                continue
            report['titles_found'] += 1
            if not execute:
                continue
            with sessions.begin() as session:
                paper = session.scalar(select(Paper).where(Paper.id == record.id, Paper.status == 'ready',
                    Paper.title == record.title, Paper.sha256 == record.sha256,
                    Paper.original_filename == record.original_filename, ~Paper.source.has()).with_for_update())
                if paper is not None:
                    paper.title = result.title
                    paper.updated_at = database_time(session)
                    report['updated'] += 1


def main() -> None:
    parser = argparse.ArgumentParser(description='Extract titles for existing filename-named uploaded PDFs; preview by default.')
    parser.add_argument('--execute', action='store_true', help='Save extracted titles; never changes files or evidence chunks.')
    arguments = parser.parse_args()
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        print(json.dumps(refresh_titles(create_session_factory(engine), settings, execute=arguments.execute)))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
