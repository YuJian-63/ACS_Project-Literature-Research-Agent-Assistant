"""Run the copy workload to completion; quality and execution are separate results."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import time

from cache_quality import check_answer, prefix_caching_from_metrics, summarize
from long_workload import COLD_POSITIONS, PROTOCOL, WARMUP_POSITIONS, workload, workload_hash
from metrics_sampler import boundary_metrics_summary, selected_metrics
from model_client import ModelClient, ServiceError

MAX_INPUT = 32767
OUTPUT_BUDGET = 4096
CODE_FILES = ("long_quality.py", "long_workload.py", "cache_quality.py", "model_client.py", "metrics_sampler.py")


def save(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def first_difference(actual, expected, path="$"):
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in expected:
            if key not in actual:
                return path + "." + key + " is missing"
            problem = first_difference(actual[key], expected[key], path + "." + key)
            if problem:
                return problem
        extra = actual.keys() - expected.keys()
        return path + " unexpected keys: " + str(sorted(extra)) if extra else None
    if isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path} has {len(actual)} records; expected {len(expected)}"
        for index, (a, b) in enumerate(zip(actual, expected)):
            problem = first_difference(a, b, f"{path}[{index}]")
            if problem:
                return problem
        return None
    same_type = type(actual) is type(expected) or type(actual) in (int, float) and type(expected) in (int, float)
    if same_type and actual == expected:
        return None
    return f"{path}: expected {json.dumps(expected)[:160]}, got {json.dumps(actual)[:160]}"


def validate_answer(result, expected):
    passed, problem = check_answer(result.content, expected)
    finish = result.response["choices"][0]["finish_reason"]
    if finish != "stop":
        return False, "Output did not finish normally: " + str(finish)
    if not passed:
        try:
            detail = first_difference(json.loads(result.content), expected)
            problem = str(problem) + "; " + str(detail)
        except (ValueError, TypeError):
            pass
    usage = result.usage
    if (type(usage.get("prompt_tokens")) is not int or not 0 < usage["prompt_tokens"] <= MAX_INPUT
            or type(usage.get("completion_tokens")) is not int or not 0 < usage["completion_tokens"] <= OUTPUT_BUDGET):
        return False, "Missing or out-of-budget actual token counts"
    return passed, problem


def observe(client, case):
    started = time.perf_counter()
    try:
        result = client.chat(case["messages"], stream=True, max_tokens=OUTPUT_BUDGET,
                             cache_salt=case["cache_salt"], response_format={"type": "json_object"})
        passed, problem = validate_answer(result, case["expected"])
        return {"success": True, "quality_passed": passed, "quality_error": problem,
                "content": result.content, "response": result.response, "usage": result.usage,
                "elapsed_s": result.elapsed_s, "ttft_s": result.ttft_s, "tpot_s": result.tpot_s,
                "finish_reason": result.response["choices"][0]["finish_reason"]}
    except (ServiceError, ValueError, KeyError, IndexError, TypeError) as exc:
        return {"success": False, "quality_passed": False, "error": str(exc),
                "elapsed_s": time.perf_counter() - started}


def run(client, directory, service_job_id, settings):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any((directory / name).exists() for name in ("summary.json", "answers.jsonl", "warmup.json")):
        raise ValueError("Choose a fresh results directory; previous evidence will not be overwritten")
    cases = workload()
    save(directory / "workload.json", cases)
    save(directory / "service_config.json", settings)
    counts, references, rows, warmups, boundaries = [], [], [], [], []
    report = {
        "status": "preflight", "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_job_id": os.getenv("SLURM_JOB_ID"), "service_job_id": service_job_id,
        "protocol": PROTOCOL, "client_host": socket.gethostname(), "service_config": settings,
        "purpose": "Paired long-copy supplement; historical datasets and results retained separately",
        "measurement_code_sha256": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in CODE_FILES},
        "prefix_caching_enabled": None, "condition": "prefix_cache_on", "base_url": client.base_url,
        "model": client.model, "concurrency": 1, "trials": 4, "cases_per_trial": 6,
        "workload_sha256": workload_hash(), "input_token_counts": counts,
        "reference_output_token_counts": references, "output_budget": OUTPUT_BUDGET,
        "max_input_tokens": MAX_INPUT, "metrics_sampling": "experiment-boundaries", "metrics_requests": 0,
        "natural_eos": True, "temperature": 0, "thinking": False,
        "warmup_requests": 3, "warmup_target_document_requests": 2, "warmup_positions": WARMUP_POSITIONS,
        "warmup_quality_policy": "record-only; never abort measured requests for a warmup answer mismatch",
        "cache_isolation": "Fresh cache_salt per trial and document family, shared only by that family's three tasks",
        "cold_question_positions": COLD_POSITIONS, "first_question_included": True,
        "quality_rule": "All 16 records, requested keys, values, JSON types, exact quotes and citations must match",
        "scope": "Synthetic extraction/copy tasks; not a reasoning or real Agent benchmark",
        "resource_scope": "Two cumulative-counter snapshots; no inference memory or queue/KV peaks", "stages": [],
    }

    def persist():
        report["measured_requests_completed"] = len(rows)
        report["sample_quality_gate_passed"] = len(rows) == 24 and all(r["success"] and r["quality_passed"] for r in rows)
        report["quality_failed_requests"] = sum(not r["quality_passed"] for r in rows)
        report["request_errors"] = sum(not r["success"] for r in rows)
        if rows:
            report["summary"] = summarize(rows)
            cold = [r for r in rows if r["position"] in COLD_POSITIONS]
            following = [r for r in rows if r["position"] not in COLD_POSITIONS]
            if cold:
                report["first_questions"] = summarize(cold)
            if following:
                report["following_questions"] = summarize(following)
        save(directory / "summary.json", report)

    def snapshot(stage):
        report["metrics_requests"] += 1
        row = {"stage": stage, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "values": {}}
        raw = ""
        try:
            raw = client.get_text("metrics", server_root=True)
            row["values"] = selected_metrics(raw)
            row["prefix_caching_enabled"] = prefix_caching_from_metrics(raw)
        except (ServiceError, ValueError) as exc:
            row["error"] = str(exc)
        (directory / ("server-metrics-" + stage + ".txt")).write_text(raw, encoding="utf-8")
        boundaries.append(row)
        (directory / "metrics-boundaries.jsonl").write_text(
            "".join(json.dumps(b) + "\n" for b in boundaries), encoding="utf-8")

    persist()
    try:
        for case in cases:
            with client._open(client.base_url[:-3] + "/tokenize", {
                "model": client.model, "messages": case["messages"],
                "chat_template_kwargs": {"enable_thinking": False},
            }) as response:
                tokenized = json.load(response)
            counts.append(tokenized["count"])
            save(directory / "tokenization.json", {"input_counts": counts, "reference_output_counts": references})
            if (tokenized["max_model_len"] != settings["max_model_len"] or counts[-1] > MAX_INPUT
                    or counts[-1] + OUTPUT_BUDGET > settings["max_model_len"]):
                raise ServiceError(f"Input/context budget exceeded for {case['id']}: {counts[-1]}")
            with client._open(client.base_url[:-3] + "/tokenize", {
                "model": client.model, "prompt": json.dumps(case["expected"], separators=(",", ":")),
                "add_special_tokens": False,
            }) as response:
                references.append(json.load(response)["count"])
            save(directory / "tokenization.json", {"input_counts": counts, "reference_output_counts": references})
            if not 512 <= references[-1] <= 3000:
                raise ServiceError("Reference answer must be 512..3000 tokens: " + case["id"])
        print("PROTOCOL=" + PROTOCOL, flush=True)
        print("TOKEN_COUNTS=" + json.dumps({"inputs": counts, "compact_reference_outputs": references}), flush=True)
        report["status"] = "warmup"
        tiny = {"success": True}
        try:
            client.chat([{"role": "user", "content": "1+1? Answer only 2."}], stream=True, max_tokens=16)
        except (ServiceError, ValueError, KeyError, IndexError, TypeError) as exc:
            tiny = {"success": False, "error": str(exc)}
        for position in WARMUP_POSITIONS:
            case = cases[position]
            observed = observe(client, dict(case, cache_salt=secrets.token_urlsafe(32)))
            warmups.append(dict(observed, case_id=case["id"], position=position))
            save(directory / "warmup.json", {
                "measured": False, "requests": 1 + len(warmups), "planned_requests": 3,
                "target_document_requests": 2, "completed_document_requests": len(warmups),
                "quality_passed": tiny["success"] and all(w["quality_passed"] for w in warmups),
                "quality_policy": "record-only", "small_warmup": tiny, "responses": warmups,
            })
            print(f"WARMUP case={case['id']} success={observed['success']} quality={observed['quality_passed']}", flush=True)
        report["warmup_quality_gate_passed"] = tiny["success"] and all(w["quality_passed"] for w in warmups)
        print("WARMUP_COMPLETE=3 unmeasured attempts; quality is recorded, measured requests will continue", flush=True)
        snapshot("before")
        report["prefix_caching_enabled"] = boundaries[0].get("prefix_caching_enabled")
        report["status"] = "running"
        persist()
        print("SERVER_METRICS_SAMPLING=experiment-boundaries-only; two attempts, outside timing", flush=True)
        with (directory / "answers.jsonl").open("w", encoding="utf-8") as output:
            for trial in range(1, 5):
                salts = {case["document_family"]: secrets.token_urlsafe(32) for case in cases}
                stage_rows = []
                started = time.perf_counter()
                for position, case in enumerate(cases):
                    row = {"trial": trial, "position": position, "case_id": case["id"],
                           "condition": "prefix_cache_on", "document_family": case["document_family"],
                           "task_type": case["task_type"], "expected": case["expected"]}
                    row.update(observe(client, dict(case, cache_salt=salts[case["document_family"]])))
                    rows.append(row)
                    stage_rows.append(row)
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
                    output.flush()
                    print(f"REQUEST trial={trial} case={case['id']} success={row['success']} quality={row['quality_passed']}", flush=True)
                report["stages"].append({"trial": trial, "wall_s": time.perf_counter() - started, **summarize(stage_rows)})
                persist()
        report["status"] = "complete"
    except BaseException as exc:
        report["status"] = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "execution_error"
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        if boundaries:
            snapshot("after")
            report["engine_metrics"] = boundary_metrics_summary(boundaries)
            report["counter_window_matches_24_requests"] = report["engine_metrics"]["counter_deltas"]["request_prefill_kv_computed_tokens_count"] == 24
            report["resource_metrics_valid"] = len(boundaries) == 2 and all(
                not b.get("error") and b.get("prefix_caching_enabled") is True for b in boundaries)
        else:
            report["resource_metrics_valid"] = False
        persist()
    print("METRICS_REQUESTS=" + str(report["metrics_requests"]), flush=True)
    print("RUN_COMPLETE measured_requests=" + str(len(rows)), flush=True)
    print("RESULT_DIR=" + str(directory), flush=True)
    print("QUALITY_GATE=" + json.dumps({"sample_quality_gate_passed": report["sample_quality_gate_passed"],
                                         "quality_failed_requests": report["quality_failed_requests"],
                                         "request_errors": report["request_errors"]}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-job-id", required=True)
    parser.add_argument("--service-config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    settings = json.loads(Path(args.service_config).read_text(encoding="utf-8-sig"))
    if settings.get("enable_prefix_caching") is not True or settings.get("max_model_len") != 36864:
        parser.error("Use the agreed 36864-token context and APC enabled")
    run(ModelClient(timeout=180), Path(args.output_dir), args.service_job_id, settings)
    # Successful execution means all planned requests were recorded. Quality remains
    # a separate explicit gate; the comparison command still rejects wrong answers.


if __name__ == "__main__":
    main()
