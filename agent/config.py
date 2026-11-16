"""Local environment shared by API probes and the workflow."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"


def load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)


def require_env(name: str) -> str:
    load_env()
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} in agent/.env")
    return value
