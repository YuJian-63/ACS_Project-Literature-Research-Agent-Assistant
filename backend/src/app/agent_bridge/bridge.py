"""Standalone entry point, executed only by the dedicated Agent interpreter."""

import json
import os
import resource
import sys
from pathlib import Path


def main():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Agent requires Python 3.12")
    # Hard per-file ceiling complements the parent's tighter polling limits.
    file_limit = 16 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    task_path, result_path = map(Path, sys.argv[1:3])
    agent_dir = Path(__file__).resolve().parents[4] / "agent"
    os.chdir(agent_dir)
    sys.path.insert(0, str(agent_dir))
    from baseline import run_task

    task = json.loads(task_path.read_text(encoding="utf-8"))
    result = run_task(task, persist=False)
    result_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
