"""Run the five Agent examples under the five ablation configurations."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp

import baseline
import extension
from apis.library import LibraryClient, search_library
from config import ROOT, RUNS_DIR, load_env
from schemas import Task

CASES = ("library-qa", "qa", "summary", "review", "discovery")
CONFIGS = ("baseline", "rag", "rag-planner", "rag-reflection", "full")


def main() -> int:
    load_env()
    tasks = {
        case: (ROOT / "examples" / f"{case}.json").read_text(encoding="utf-8")
        for case in CASES
    }
    username = os.getenv("AGENT_LIBRARY_USERNAME")
    password = os.getenv("AGENT_LIBRARY_PASSWORD")
    if bool(username) != bool(password):
        raise SystemExit("请同时提供论文库用户名和密码。")
    connect = LibraryClient.login_from_cli if username else LibraryClient.from_env
    library = connect()
    if library is None:
        raise SystemExit("SkillOpt 题需要论文库授权。用法: ./agent/run.sh '用户名' '密码'")
    if not search_library(library.base_url, library.token, "SkillOpt", limit=1)["items"]:
        raise SystemExit("当前账号的论文库中未找到 SkillOpt，请先上传原文。")

    runs = RUNS_DIR / "ablation"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    batch = Path(mkdtemp(prefix=f"{stamp}-", dir=runs))
    print(f"批次目录 {batch}", flush=True)
    failed = 0
    count = 0
    for case, raw_task in tasks.items():
        for config in CONFIGS:
            count += 1
            task = Task.model_validate_json(raw_task)
            folder = batch / case / config
            folder.mkdir(parents=True)
            print(f"[{count}/{len(tasks) * len(CONFIGS)}] {case}/{config}", flush=True)
            try:
                client = None
                if case in {"library-qa", "discovery"}:
                    # Library grants are short lived. Reuse the preflight grant once.
                    client = library if count == 1 else connect()
                if config == "baseline":
                    result = baseline.run_task(task, library=client)
                else:
                    result = extension.run_task(
                        task,
                        library=client,
                        planner=config in {"rag-planner", "full"},
                        reflection=config in {"rag-reflection", "full"},
                    )
                record = result.model_dump(mode="json", exclude={"trace"})
                trace = result.trace
            except (Exception, SystemExit) as exc:  # noqa: BLE001 - isolate this run
                # A login or runner failure can happen before a TaskResult exists.
                record = {
                    "task_id": task.task_id,
                    "question": task.question,
                    "stop_reason": "runner_error",
                    "errors": [{"stage": "runner", "type": type(exc).__name__}],
                }
                if isinstance(exc, SystemExit):
                    print(str(exc), file=sys.stderr)
                trace = []
            for filename, data in (("trace.json", trace), ("result.json", record)):
                (folder / filename).write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            reason = record["stop_reason"]
            print(f"  {reason}", flush=True)
            if reason not in {"completed", "partial"}:
                failed += 1
    print(f"共 {count} 组，失败 {failed} 组。结果目录 {batch}")
    return int(failed > 0)


if __name__ == "__main__":
    sys.exit(main())
