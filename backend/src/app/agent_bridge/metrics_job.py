import importlib.util
from pathlib import Path


def main():
    spec = importlib.util.spec_from_file_location("research_job", Path(__file__).with_name("research_job.py"))
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    original = job.run_research

    def run_research(*args, **kwargs):
        try:
            from model_telemetry import install

            install()
        except Exception:
            pass
        return original(*args, **kwargs)

    job.run_research = run_research
    return job.main()


if __name__ == "__main__":
    raise SystemExit(main())
