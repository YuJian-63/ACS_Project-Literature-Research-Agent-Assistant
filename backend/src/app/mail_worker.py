import argparse
import logging
import time

from app.auth.mail import MailWorker
from app.config import Settings
from app.db.session import create_database_engine, create_session_factory


def main():
    parser = argparse.ArgumentParser(description="Deliver encrypted account mail from the durable outbox")
    parser.add_argument("--once", action="store_true", help="Process at most one queued delivery")
    args = parser.parse_args()
    logger = logging.getLogger("app.mail_worker")
    engine = None
    try:
        settings = Settings()
        from app.auth.security import check_config
        check_config(settings)
        engine = create_database_engine(settings)
        worker = MailWorker(create_session_factory(engine), settings)
        while True:
            try:
                worked = worker.run_once()
            except Exception:
                logger.warning("Mail worker unavailable; check configuration and database health")
                if args.once:
                    return 1
                worked = False
            if args.once:
                return 0
            if not worked:
                time.sleep(2)
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.error("Mail worker could not start; check configuration")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
