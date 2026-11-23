"""Prepare and bind quick max_num_batched_tokens screening; no TACC calls."""

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

import gdn_experiment as gdn
import prefill_experiment as common

ROOT = Path(__file__).resolve().parent
SERVE = ROOT / "qwen-private-serve"
CLIENT = ROOT / "qwen-private-serial-cache"
PLAN = ROOT / "results/prefill-screen-plan.json"
BASE = dict(common.BASE_CONFIG, profile="private-prefill-screen")
BUDGETS = (2048, 4096, 8192)
PROTOCOL = "serial-long-copy-screen-v1"


def settings(budget):
    if budget not in BUDGETS:
        raise ValueError("budget must be 2048, 4096 or 8192")
    return dict(BASE, max_num_batched_tokens=budget)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def marker(text, name):
    matches = re.findall(r"^" + re.escape(name) + r"=(.+)$", text, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("Expected one " + name + " in service log")
    return matches[0].strip()


def select(budget):
    current = read_json(SERVE / "service_config.json")
    allowed = [settings(value) for value in BUDGETS]
    allowed += [dict(common.BASE_CONFIG, profile="public-reference-gdn"),
                dict(common.BASE_CONFIG, profile="agent-public-integration-v1", agent_telemetry=True),
                dict(common.BASE_CONFIG, profile="private-attention-e01", attention_backend=None)]
    if current not in allowed:
        raise ValueError("Unexpected active configuration; finish the current experiment first")
    if read_json(ROOT / "variant.json") != gdn.manifest("baseline"):
        raise ValueError("Prefill screening requires the unchanged baseline source")
    for name, digest in gdn.manifest("baseline")["source_sha256"].items():
        if hashlib.sha256((ROOT / "vllm-src" / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Private source differs from baseline: " + name)
    value = settings(budget)
    write_json(SERVE / "service_config.json", value)
    write_json(CLIENT / "service_config.json", value)
    (SERVE / "runtime-mode.txt").write_text("private\n", encoding="utf-8")
    (CLIENT / "measurement-mode.txt").write_text("quick\n", encoding="utf-8")
    (CLIENT / "service-job-id.txt").write_text("UNSET\n", encoding="utf-8")
    (CLIENT / "server-url.txt").write_text("http://NODE:8000/v1\n", encoding="utf-8")
    plan = {
        "experiment": "prefill-budget-screen-v1",
        "protocol": PROTOCOL,
        "status": "prepared_not_tacc_measured",
        "budget": budget,
        "budgets_to_compare": list(BUDGETS),
        "changed_factor": "max_num_batched_tokens",
        "unchanged_factors": ["source", "model", "dtype", "TP", "context", "seq", "APC", "runtime", "workload"],
        "workload_scope": "4 cases x 2 trials = 8 measured requests; quick screening only",
        "metrics_sampling": "two boundary reads outside timing",
        "full_v2_confirmation": False,
    }
    write_json(PLAN, plan)
    print(f"PREFILL_SCREEN_BUDGET={budget} RUNTIME=private CLIENT_MODE=quick")
    print("No source change and no build required if the unchanged private baseline build is valid.")


def bind(budget, service_job_id, service_log):
    value = settings(budget)
    if not str(service_job_id).isdigit():
        raise ValueError("GPU service job ID must be numeric")
    if read_json(CLIENT / "service_config.json") != value:
        raise ValueError("Select this budget before binding")
    text = Path(service_log).read_text(encoding="utf-8-sig")
    if marker(text, "SERVICE_JOB_ID") != str(service_job_id):
        raise ValueError("Wrong service log")
    if "Application startup complete." not in text:
        raise ValueError("Service is not ready")
    if "PRIVATE VLLM / PUBLIC DEPENDENCIES CHECK PASSED" not in text:
        raise ValueError("Expected private runtime")
    source = json.loads(marker(text, "PRIVATE_SOURCE_VARIANT"))
    if source.get("variant") != "baseline":
        raise ValueError("Prefill screen requires baseline source")
    rows = re.findall(r"non-default args: (\{[^\r\n]+\})", text)
    if len(rows) != 1:
        raise ValueError("Need one startup argument record")
    arguments = ast.literal_eval(rows[0])
    if arguments.get("max_num_batched_tokens") != budget:
        raise ValueError("Actual max_num_batched_tokens differs from selected budget")
    if "speculative_config" in arguments:
        raise ValueError("Prefill screen must not use speculative decoding")
    (CLIENT / "service-job-id.txt").write_text(str(service_job_id) + "\n", encoding="utf-8")
    base_url = marker(text, "SERVICE_BASE_URL")
    (CLIENT / "server-url.txt").write_text(base_url + "\n", encoding="utf-8")
    plan = read_json(PLAN)
    plan.update(status="service_ready_cpu_not_submitted", service_job_id=str(service_job_id), base_url=base_url)
    write_json(PLAN, plan)
    print(f"BOUND_PREFILL_SCREEN_BUDGET={budget} GPU_JOB={service_job_id} BASE_URL={base_url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selector = commands.add_parser("select")
    selector.add_argument("budget", type=int, choices=BUDGETS)
    binder = commands.add_parser("bind")
    binder.add_argument("budget", type=int, choices=BUDGETS)
    binder.add_argument("--service-job-id", required=True)
    binder.add_argument("--service-log", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "select":
            select(args.budget)
        else:
            bind(args.budget, args.service_job_id, args.service_log)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        parser.exit(2, "ERROR: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
