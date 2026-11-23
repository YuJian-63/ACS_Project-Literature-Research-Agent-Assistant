"""Measure fixed-concurrency streaming inference without modifying the old client."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import statistics
import time

from cache_quality import check_answer, prefix_caching_from_metrics
from metrics_sampler import boundary_metrics_summary, selected_metrics
from model_client import ModelClient, ServiceError
from quick_workload import workload, workload_hash


PROTOCOL = "concurrent-long-copy-screen-v1"
MAX_INPUT_TOKENS = 32767
OUTPUT_BUDGET = 4096
TRIALS = 2
CASES_PER_TRIAL = 4
MEASURED_REQUESTS = TRIALS * CASES_PER_TRIAL
WARMUP_POSITIONS = (0, 2)
CODE_FILES = (
    "concurrency_quality.py", "quick_workload.py", "long_workload.py",
    "cache_quality.py", "model_client.py", "metrics_sampler.py",
)


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def percentile(values, fraction):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    weight = position - low
    return values[low] * (1 - weight) + values[high] * weight


def stats(values):
    values = [value for value in values if value is not None]
    if not values:
        return {"mean": None, "median": None, "p50": None, "p95": None}
    return {
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
    }


def summarize(rows, wall_s=None):
    successful = [row for row in rows if row.get("success")]
    quality = [row for row in rows if row.get("quality_passed")]
    prompt_tokens = [row.get("usage", {}).get("prompt_tokens") for row in successful]
    completion_tokens = [row.get("usage", {}).get("completion_tokens") for row in successful]
    result = {
        "attempted": len(rows),
        "successful": len(successful),
        "quality_passed": len(quality),
        "quality_accuracy": len(quality) / len(rows) if rows else None,
        "prompt_tokens": sum(prompt_tokens) if prompt_tokens and all(isinstance(n, int) for n in prompt_tokens) else None,
        "completion_tokens": sum(completion_tokens) if completion_tokens and all(isinstance(n, int) for n in completion_tokens) else None,
        "elapsed_s": stats([row.get("elapsed_s") for row in successful]),
        "ttft_s": stats([row.get("ttft_s") for row in successful]),
        "tpot_s": stats([row.get("tpot_s") for row in successful]),
    }
    if result["prompt_tokens"] is not None and result["completion_tokens"] is not None:
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
    else:
        result["total_tokens"] = None
    if wall_s is not None:
        result["wall_s"] = wall_s
        result["requests_per_s"] = len(successful) / wall_s if wall_s > 0 else None
        result["output_tokens_per_s"] = (
            result["completion_tokens"] / wall_s
            if result["completion_tokens"] is not None and wall_s > 0 else None
        )
    return result


def validate(result):
    finish = result.response["choices"][0]["finish_reason"]
    passed, problem = check_answer(result.content, result.response["expected"])
    usage = result.usage
    if finish != "stop":
        return False, "Output did not finish normally: " + str(finish)
    if (not isinstance(usage.get("prompt_tokens"), int)
            or not 0 < usage["prompt_tokens"] <= MAX_INPUT_TOKENS
            or not isinstance(usage.get("completion_tokens"), int)
            or not 0 < usage["completion_tokens"] <= OUTPUT_BUDGET):
        return False, "Missing or out-of-budget actual token counts"
    return passed, problem


def observe(client, case, cache_salt, metadata):
    started = time.perf_counter()
    try:
        result = client.chat(
            case["messages"], stream=True, max_tokens=OUTPUT_BUDGET,
            cache_salt=cache_salt, response_format={"type": "json_object"},
        )
        # ChatResult is deliberately not modified.  Keep the expected object in
        # the local metadata so the assembled OpenAI-compatible response remains
        # exactly what the server returned.
        result_wrapper = type("ResultWithExpected", (), {
            "content": result.content,
            "response": dict(result.response, expected=case["expected"]),
            "usage": result.usage,
        })()
        passed, problem = validate(result_wrapper)
        finish = result.response["choices"][0]["finish_reason"]
        return {
            **metadata, "success": True, "quality_passed": passed,
            "quality_error": problem, "content": result.content,
            "response": result.response, "usage": result.usage,
            "elapsed_s": result.elapsed_s, "ttft_s": result.ttft_s,
            "tpot_s": result.tpot_s, "finish_reason": finish,
        }
    except (ServiceError, ValueError, KeyError, IndexError, TypeError) as exc:
        return {
            **metadata, "success": False, "quality_passed": False,
            "error": str(exc), "elapsed_s": time.perf_counter() - started,
        }


def snapshot(client, directory, stage, boundaries):
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
        "".join(json.dumps(item) + "\n" for item in boundaries), encoding="utf-8"
    )
    return row


def run(client, directory, service_job_id, settings, concurrency):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any((directory / name).exists() for name in ("summary.json", "answers.jsonl", "warmup.json")):
        raise ValueError("Choose a fresh results directory; previous evidence will not be overwritten")
    if concurrency not in (1, 2, 4):
        raise ValueError("This screen supports concurrency 1, 2, or 4")
    if settings.get("max_num_seqs", 0) < concurrency:
        raise ValueError("Server max_num_seqs is smaller than the requested client concurrency")
    if settings.get("max_model_len") != 36864 or settings.get("enable_prefix_caching") is not True:
        raise ValueError("Use context 36864 and APC enabled for the concurrency screen")
    if settings.get("attention_backend") not in (None, "auto"):
        raise ValueError("Use attention_backend=null/auto; FlashInfer is not the concurrency baseline")

    cases = workload()
    save(directory / "workload.json", cases)
    save(directory / "service_config.json", settings)
    report = {
        "status": "preflight",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_job_id": os.getenv("SLURM_JOB_ID"),
        "service_job_id": str(service_job_id),
        "protocol": PROTOCOL,
        "client_host": socket.gethostname(),
        "service_config": settings,
        "measurement_code_sha256": {
            name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
            for name in CODE_FILES
        },
        "source_policy": "The client is source-neutral; run the same protocol for baseline and every candidate.",
        "base_url": client.base_url,
        "model": client.model,
        "concurrency": concurrency,
        "max_client_concurrency": 4,
        "trials": TRIALS,
        "cases_per_trial": CASES_PER_TRIAL,
        "measured_requests_planned": MEASURED_REQUESTS,
        "waves_per_trial": (CASES_PER_TRIAL + concurrency - 1) // concurrency,
        "workload_sha256": workload_hash(),
        "output_budget": OUTPUT_BUDGET,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "metrics_sampling": "experiment-boundaries",
        "metrics_requests": 0,
        "natural_eos": True,
        "temperature": 0,
        "thinking": False,
        "warmup_requests": 3,
        "warmup_positions": list(WARMUP_POSITIONS),
        "warmup_quality_policy": "record-only; measured waves continue after a warmup mismatch",
        "cache_isolation": "One fresh cache_salt per document family and trial; reused within that trial",
        "quality_rule": "All requested records, values, JSON types, exact quotes and citations must match",
        "resource_scope": "Two vLLM cumulative-counter snapshots; no GPU/KV sidecar sampling",
        "stages": [],
        "waves": [],
    }
    rows = []
    boundaries = []

    def persist():
        report["measured_requests_completed"] = len(rows)
        report["sample_quality_gate_passed"] = (
            len(rows) == MEASURED_REQUESTS
            and all(row.get("success") and row.get("quality_passed") for row in rows)
        )
        report["quality_failed_requests"] = sum(not row.get("quality_passed") for row in rows)
        report["request_errors"] = sum(not row.get("success") for row in rows)
        if rows:
            report["summary"] = summarize(rows, report.get("measured_wall_s"))
            report["by_case"] = {
                case_id: summarize([row for row in rows if row["case_id"] == case_id])
                for case_id in sorted({row["case_id"] for row in rows})
            }
        save(directory / "summary.json", report)

    try:
        token_counts = []
        references = []
        for case in cases:
            with client._open(client.base_url[:-3] + "/tokenize", {
                "model": client.model, "messages": case["messages"],
                "chat_template_kwargs": {"enable_thinking": False},
            }) as response:
                tokenized = json.load(response)
            token_counts.append(tokenized["count"])
            if (tokenized["max_model_len"] != settings["max_model_len"]
                    or tokenized["count"] > MAX_INPUT_TOKENS
                    or tokenized["count"] + OUTPUT_BUDGET > settings["max_model_len"]):
                raise ServiceError("Input/context budget exceeded for " + case["id"])
            with client._open(client.base_url[:-3] + "/tokenize", {
                "model": client.model, "prompt": json.dumps(case["expected"], separators=(",", ":")),
                "add_special_tokens": False,
            }) as response:
                reference = json.load(response)["count"]
            references.append(reference)
            if not 512 <= reference <= 3000:
                raise ServiceError("Reference answer must be 512..3000 tokens: " + case["id"])
        report["input_token_counts"] = token_counts
        report["reference_output_token_counts"] = references
        save(directory / "tokenization.json", {
            "input_counts": token_counts, "reference_output_counts": references,
        })
        print("PROTOCOL=" + PROTOCOL, flush=True)
        print("CONCURRENCY_LEVEL=" + str(concurrency), flush=True)
        print("TOKEN_COUNTS=" + json.dumps({"inputs": token_counts, "compact_reference_outputs": references}), flush=True)

        tiny = {"success": True}
        try:
            client.chat([{"role": "user", "content": "1+1? Answer only 2."}], stream=True, max_tokens=16)
        except (ServiceError, ValueError, KeyError, IndexError, TypeError) as exc:
            tiny = {"success": False, "error": str(exc)}
        warmups = []
        for position in WARMUP_POSITIONS:
            case = cases[position]
            warmup = observe(client, case, secrets.token_urlsafe(32), {
                "case_id": case["id"], "position": position, "warmup": True,
            })
            warmups.append(warmup)
            save(directory / "warmup.json", {
                "measured": False, "requests": 1 + len(warmups), "planned_requests": 3,
                "quality_passed": tiny["success"] and all(item["quality_passed"] for item in warmups),
                "quality_policy": "record-only", "small_warmup": tiny, "responses": warmups,
            })
            print("WARMUP case=" + case["id"] + " success=" + str(warmup["success"])
                  + " quality=" + str(warmup["quality_passed"]), flush=True)
        report["warmup_quality_gate_passed"] = tiny["success"] and all(item["quality_passed"] for item in warmups)
        print("WARMUP_COMPLETE=3 unmeasured attempts; measured waves continue", flush=True)

        before = snapshot(client, directory, "before", boundaries)
        report["metrics_requests"] = len(boundaries)
        report["prefix_caching_enabled"] = before.get("prefix_caching_enabled")
        report["metrics_boundary_gauges"] = {"before": before.get("values", {})}
        if before.get("prefix_caching_enabled") is not True:
            raise ServiceError("Could not verify APC from the before metrics snapshot")
        report["status"] = "running"
        persist()
        print("SERVER_METRICS_SAMPLING=experiment-boundaries-only; two attempts outside timing", flush=True)

        measured_started = time.perf_counter()
        with (directory / "answers.jsonl").open("w", encoding="utf-8") as output:
            sequence = 0
            for trial in range(1, TRIALS + 1):
                salts = {case["document_family"]: secrets.token_urlsafe(32) for case in cases}
                trial_rows = []
                trial_started = time.perf_counter()
                for wave_start in range(0, CASES_PER_TRIAL, concurrency):
                    wave = wave_start // concurrency + 1
                    wave_cases = cases[wave_start:wave_start + concurrency]
                    wave_started = time.perf_counter()
                    future_rows = {}
                    with ThreadPoolExecutor(max_workers=concurrency) as pool:
                        for offset, case in enumerate(wave_cases):
                            sequence += 1
                            metadata = {
                                "trial": trial, "wave": wave, "sequence": sequence,
                                "condition": "prefix_cache_on", "case_id": case["id"],
                                "position": wave_start + offset, "concurrency": concurrency,
                                "warmup": False, "expected": case["expected"],
                            }
                            future = pool.submit(
                                observe, client, case, salts[case["document_family"]], metadata,
                            )
                            future_rows[future] = metadata
                        wave_results = [future.result() for future in as_completed(future_rows)]
                    wave_results.sort(key=lambda row: row["sequence"])
                    wave_wall = time.perf_counter() - wave_started
                    report["waves"].append({
                        "trial": trial, "wave": wave, "concurrency": concurrency,
                        "wall_s": wave_wall, "summary": summarize(wave_results),
                    })
                    for row in wave_results:
                        rows.append(row)
                        trial_rows.append(row)
                        output.write(json.dumps(row, ensure_ascii=False) + "\n")
                        output.flush()
                        print("REQUEST trial=" + str(trial) + " wave=" + str(wave)
                              + " case=" + row["case_id"] + " success=" + str(row["success"])
                              + " quality=" + str(row["quality_passed"]), flush=True)
                trial_wall = time.perf_counter() - trial_started
                report["stages"].append({"trial": trial, "wall_s": trial_wall, **summarize(trial_rows, trial_wall)})
                persist()
        report["measured_wall_s"] = time.perf_counter() - measured_started
        report["status"] = "complete"
    except BaseException as exc:
        report["status"] = "execution_error"
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        if boundaries:
            after = snapshot(client, directory, "after", boundaries)
            report["metrics_requests"] = len(boundaries)
            report.setdefault("metrics_boundary_gauges", {})["after"] = after.get("values", {})
            report["measurement_window_utc"] = {
                "start": boundaries[0]["timestamp_utc"],
                "end": boundaries[-1]["timestamp_utc"],
            }
            report["engine_metrics"] = boundary_metrics_summary(boundaries)
            deltas = report["engine_metrics"]["counter_deltas"]
            report["counter_window_matches_measured_requests"] = (
                deltas.get("request_prefill_kv_computed_tokens_count") == len(rows)
            )
            report["resource_metrics_valid"] = (
                len(boundaries) == 2
                and not before.get("error")
                and not after.get("error")
            )
        else:
            report["resource_metrics_valid"] = False
        persist()
    print("METRICS_REQUESTS=" + str(report["metrics_requests"]), flush=True)
    print("RUN_COMPLETE measured_requests=" + str(len(rows)) + " PROFILE=concurrency", flush=True)
    print("RESULT_DIR=" + str(directory), flush=True)
    print("QUALITY_GATE=" + json.dumps({
        "sample_quality_gate_passed": report["sample_quality_gate_passed"],
        "quality_failed_requests": report["quality_failed_requests"],
        "request_errors": report["request_errors"],
    }), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, required=True, choices=(1, 2, 4))
    parser.add_argument("--service-job-id", required=True)
    parser.add_argument("--service-config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    settings = json.loads(Path(args.service_config).read_text(encoding="utf-8-sig"))
    run(ModelClient(timeout=300), Path(args.output_dir), args.service_job_id, settings, args.concurrency)


if __name__ == "__main__":
    main()
