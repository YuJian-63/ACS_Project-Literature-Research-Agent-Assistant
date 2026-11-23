import argparse
import logging
import signal
from threading import Event

from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.evaluations.contracts import EvaluationFailure
from app.evaluations.evidence import prepare_evidence
from app.evaluations.judge import evaluate
from app.evaluations.service import claim_evaluation, configuration, digest, finish_evaluation, save_evidence
from app.sources.access import source_permit
from app.sources.arxiv import ArxivClient
from app.sources.arxiv_transport import SupervisedArxivTransport

logger = logging.getLogger(__name__)


class EvaluationWorker:
    def __init__(self, sessions, settings, *, judge=evaluate):
        self.sessions, self.settings, self.judge = sessions, settings, judge
        self.arxiv_client = ArxivClient(SupervisedArxivTransport(settings.arxiv_contact_email,
            lambda: source_permit(sessions))) if settings.arxiv_configured else None

    def run_once(self) -> bool:
        if not self.settings.evaluation_configured:
            return False
        claim = claim_evaluation(self.sessions, self.settings)
        if claim is None:
            return False
        try:
            if digest(claim.config) != claim.config_sha256 or digest(configuration(self.settings)) != claim.config_sha256:
                raise EvaluationFailure("EVALUATION_CONFIG_CHANGED")
            if digest(claim.input_payload) != claim.input_sha256:
                raise EvaluationFailure("EVALUATION_INPUT_CHANGED")
            evidence = claim.evidence
            if evidence is not None and digest(evidence) != claim.evidence_sha256:
                raise EvaluationFailure("EVALUATION_EVIDENCE_CHANGED")
            if evidence is None:
                evidence = prepare_evidence(claim.input_payload, self.settings, arxiv_client=self.arxiv_client)
                if not save_evidence(self.sessions, claim, evidence):
                    return True
            report, usage = self.judge(self.settings, claim.input_payload, evidence, claim.config)
            finish_evaluation(self.sessions, claim, report=report, usage=usage)
        except EvaluationFailure as error:
            finish_evaluation(self.sessions, claim, error=error)
        except Exception as error:
            logger.warning("Evaluation interrupted: error_type=%s; check worker and database health", type(error).__name__)
            finish_evaluation(self.sessions, claim, error=EvaluationFailure("EVALUATION_INTERNAL_ERROR"))
        return True


def main():
    parser = argparse.ArgumentParser(description="Evaluate saved Agent results using the durable DeepSeek queue")
    parser.add_argument("--once", action="store_true", help="Process at most one queued evaluation")
    args = parser.parse_args()
    engine = None
    stopped = Event()
    try:
        settings = Settings()
        if not settings.evaluation_configured:
            logger.error("Configure EVALUATION_ENABLED, EVALUATION_MODEL and EVALUATION_API_KEY before starting the worker")
            return 1
        engine = create_database_engine(settings)
        worker = EvaluationWorker(create_session_factory(engine), settings)
        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, lambda *_: stopped.set())
        while not stopped.is_set():
            try:
                worked = worker.run_once()
            except Exception:
                logger.warning("Evaluation queue unavailable; check database health")
                if args.once:
                    return 1
                worked = False
            if args.once:
                return 0
            if not worked:
                stopped.wait(2)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.error("Evaluation worker could not start; check configuration and database health")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
