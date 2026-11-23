"""Measure one real server prefix-cache setting using fixed serial questions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import statistics
import socket
import time

from model_client import ModelClient, ServiceError
from metrics_sampler import boundary_metrics_summary, selected_metrics

MAX_INPUT_TOKENS = 32767
OUTPUT_BUDGET = 4096
PROTOCOL = "serial-gdn-boundary-v2"


def workload():
    facts = [
        "[P1:C1] Paper P1 (synthetic): sample_size=1200; dataset=X; accuracy=0.75. "
        "GPU hardware and inference latency are not reported.",
        "[P2:C1] Paper P2 (synthetic): sample_size=600; dataset=Y; accuracy=0.81. "
        "The dataset differs from P1, so these scores alone do not prove P2 superior.",
        "[P3:C1] Paper P3 (synthetic): sample_size=800; dataset=Z; median_latency_ms=42. "
        "The reported latency unit is milliseconds.",
    ]
    paragraphs = [
        f"[B{i:03d}] Background note {i}: experimental comparisons require matching "
        "datasets, evaluation splits, sample definitions and scoring rules. "
        "An absent measurement must remain unknown. This note supplies general "
        "methodological advice and does not report results for P1, P2 or P3."
        for i in range(140)
    ]
    paragraphs.insert(5, facts[0])
    paragraphs.insert(72, facts[1])
    paragraphs.append(facts[2])
    document = "\n".join(paragraphs)
    definitions = [
        ("sample", "Report P1's sample size. Use keys paper_id, sample_size, evidence_id.",
         {"paper_id": "P1", "sample_size": 1200, "evidence_id": "P1:C1"}),
        ("score", "Report P2's dataset and accuracy. Use keys dataset, accuracy, evidence_id.",
         {"dataset": "Y", "accuracy": 0.81, "evidence_id": "P2:C1"}),
        ("missing", "Report P1's GPU hardware. Use keys gpu, evidence_id; gpu must be null if unreported.",
         {"gpu": None, "evidence_id": "P1:C1"}),
        ("comparison", "Do the reported scores prove P2 better than P1? Use keys proven_better "
         "(boolean), reason (different_datasets or same_dataset), evidence_ids "
         "(sorted array of cited IDs).",
         {"proven_better": False, "reason": "different_datasets", "evidence_ids": ["P1:C1", "P2:C1"]}),
        ("latency", "Report P3's median latency in milliseconds. Use keys latency_ms, evidence_id.",
         {"latency_ms": 42, "evidence_id": "P3:C1"}),
        ("aggregate", "Add the sample sizes of P1 and P3. Use keys total_sample_size, "
         "evidence_ids (sorted array).",
         {"total_sample_size": 2000, "evidence_ids": ["P1:C1", "P3:C1"]}),
    ]
    return [{"id": name, "expected": expected, "messages": [
        {"role": "system", "content": "Use only the synthetic evidence. Return one JSON object "
         "with exactly the requested keys. Preserve numeric and boolean types. "
         "Do not invent unreported facts."},
        {"role": "user", "content": "SYNTHETIC DOCUMENT\n" + document + "\nEND DOCUMENT\n\nQuestion: " + question},
    ]} for name, question, expected in definitions]


def check_answer(text, expected):
    try:
        actual = json.loads(text)
    except (ValueError, TypeError) as exc:
        return False, "Invalid JSON: " + str(exc)
    # Dict equality alone would accept true for 1. Preserve JSON value types.
    def equal(a, b):
        if isinstance(b, dict):
            return isinstance(a, dict) and a.keys() == b.keys() and all(equal(a[k], b[k]) for k in b)
        if isinstance(b, list):
            return isinstance(a, list) and len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        if isinstance(b, bool) or b is None:
            return type(a) is type(b) and a == b
        if isinstance(b, (int, float)):
            return type(a) in (int, float) and a == b
        return type(a) is type(b) and a == b
    passed = equal(actual, expected)
    return passed, None if passed else "Answer differs from expected values, types or citations"


def summarize(rows):
    good = [r for r in rows if r["success"]]
    result = {"attempted": len(rows), "successful": len(good),
              "quality_passed": sum(r["quality_passed"] for r in rows),
              "quality_accuracy": sum(r["quality_passed"] for r in rows) / len(rows)}
    for key in ("prompt_tokens", "completion_tokens"):
        values = [r["usage"].get(key) for r in good]
        result[key] = sum(values) if values and all(type(n) is int for n in values) else None
    for key in ("elapsed_s", "ttft_s", "tpot_s"):
        values = [r[key] for r in good if r.get(key) is not None]
        result[key] = {"mean": statistics.mean(values) if values else None,
                       "median": statistics.median(values) if values else None}
    return result


def prefix_caching_from_metrics(text):
    """Read the actual server switch, rather than trusting the client label."""
    switches = set()
    for line in text.splitlines():
        if line.startswith("vllm:cache_config_info{"):
            match = re.search(r'(?:\{|,)\s*enable_prefix_caching="(True|False)"', line)
            if match:
                switches.add(match[1] == "True")
    if len(switches) != 1:
        raise ServiceError("Cannot determine one server prefix-cache setting from /metrics")
    return switches.pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-job-id", required=True)
    parser.add_argument("--trials", type=int, default=4)
    parser.add_argument("--service-config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.trials < 2:
        parser.error("use at least two repetitions of the six-question workflow")
    settings = json.loads(Path(args.service_config).read_text(encoding="utf-8-sig"))
    enabled = settings.get("enable_prefix_caching")
    if type(enabled) is not bool:
        parser.error("service-config must explicitly set enable_prefix_caching")
    condition = "prefix_cache_on" if enabled else "prefix_cache_off"
    client = ModelClient(timeout=300)
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "answers.jsonl").exists():
        parser.error("choose a fresh output directory")
    cases = workload()
    (directory / "workload.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    (directory / "service_config.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    token_counts = []
    for case in cases:
        with client._open(client.base_url[:-3] + "/tokenize", {
            "model": client.model, "messages": case["messages"],
            "chat_template_kwargs": {"enable_thinking": False},
        }) as response:
            tokens = json.load(response)
        if tokens["max_model_len"] != settings["max_model_len"] or tokens["max_model_len"] < MAX_INPUT_TOKENS + OUTPUT_BUDGET:
            raise ServiceError("Server context must match the 36864-token Agent configuration")
        if tokens["count"] > MAX_INPUT_TOKENS or tokens["count"] + OUTPUT_BUDGET > tokens["max_model_len"]:
            raise ServiceError("Workload exceeds this server's context")
        token_counts.append(tokens["count"])
    # Initialize the model's chat path before measured requests.
    client.chat([{"role": "user", "content": "1+1? Answer only 2."}], stream=True, max_tokens=16)
    # Exercise the real long-prefill path before timing it, without warming
    # any measured trial's cache namespace. Both budgets do the same warmup.
    warmed = client.chat(cases[0]["messages"], stream=True, max_tokens=OUTPUT_BUDGET,
                         cache_salt=secrets.token_urlsafe(32), response_format={"type": "json_object"})
    warmup_passed, warmup_problem = check_answer(warmed.content, cases[0]["expected"])
    if not warmup_passed or warmed.response["choices"][0]["finish_reason"] == "length":
        raise ServiceError("Long-input warmup failed quality or completeness: " + str(warmup_problem))
    (directory / "warmup.json").write_text(json.dumps({
        "measured": False, "requests": 2, "target_document_requests": 1,
        "quality_passed": True, "long_input_response": warmed.response,
    }, indent=2), encoding="utf-8")
    print("WARMUP_COMPLETE=2 unmeasured requests; measured trials use fresh cache namespaces", flush=True)
    before = client.get_text("metrics", server_root=True)
    (directory / "server-metrics-before.txt").write_text(before, encoding="utf-8")
    observed = prefix_caching_from_metrics(before)
    if observed != enabled:
        raise ServiceError("Actual server APC setting differs from the expected configuration")
    boundaries = [{"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                   "stage": "before", "values": selected_metrics(before)}]
    print("SERVER_METRICS_SAMPLING=experiment-boundaries-only; two requests, outside timing", flush=True)
    print("SERVER_PREFIX_CACHING_VERIFIED=" + str(observed).lower(), flush=True)
    print("AGENT_LIMITS=input32767/output4096/context" + str(settings["max_model_len"]), flush=True)
    report = {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "client_job_id": os.getenv("SLURM_JOB_ID"), "service_job_id": args.service_job_id,
              "protocol": PROTOCOL,
              "purpose": "Fixed-document latency and quality screening with APC enabled; source identity is verified from service evidence",
              "client_host": socket.gethostname(),
              "measurement_code_sha256": {
                  name: hashlib.sha256((Path(__file__).absolute().parent / name).read_bytes()).hexdigest()
                  for name in ("cache_quality.py", "model_client.py", "metrics_sampler.py")
              },
              "condition": condition, "prefix_caching_enabled": observed,
              "service_config": settings,
              "base_url": client.base_url, "model": client.model, "concurrency": 1,
              "trials": args.trials, "cases_per_trial": len(cases),
              "workload_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
              "input_token_counts": token_counts, "output_budget": OUTPUT_BUDGET,
              "max_input_tokens": MAX_INPUT_TOKENS, "metrics_sampling": "experiment-boundaries",
              "metrics_requests": 2,
              "natural_eos": True, "temperature": 0, "thinking": False,
              "warmup_requests": 2, "warmup_target_document_requests": 1,
              "quality_rule": "All answers must match fixed JSON facts, types and evidence IDs",
              "cache_isolation": "One fresh cache_salt per six-question trial, identical policy in both deployments",
              "first_question_included": True,
              "scope": "Synthetic fixed-document sample; quality and timings require deployment/source evidence for interpretation, not real Agent evaluation",
              "resource_scope": "Before/after cumulative counters only; no KV/queue peaks, inference memory peak, energy or whole-service CPU measurement",
              "stages": []}
    rows = []

    def persist():
        if rows:
            wall = sum(s["wall_s"] for s in report["stages"])
            report["summary"] = dict(summarize(rows), workflow_wall_s=wall,
                                     correct_tasks_per_s=sum(r["quality_passed"] for r in rows) / wall if wall else None)
            report["first_questions"] = summarize([r for r in rows if r["position"] == 0])
            following = [r for r in rows if r["position"] > 0]
            if following:
                report["following_questions"] = summarize(following)
        report["sample_quality_gate_passed"] = (
            len(rows) == args.trials * len(cases)
            and all(r["success"] and r["quality_passed"] for r in rows)
        )
        (directory / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    persist()
    with (directory / "answers.jsonl").open("w", encoding="utf-8") as output:
        for trial in range(args.trials):
            # Both deployments use this same policy. Changing the namespace
            # between trials prevents a previous trial's answers/questions
            # from warming this trial. The actual prompt bytes never change.
            salt = secrets.token_urlsafe(32)
            stage_rows = []
            started = time.perf_counter()
            for position, case in enumerate(cases):
                row = {"trial": trial + 1, "condition": condition, "case_id": case["id"],
                       "position": position, "expected": case["expected"]}
                call_started = time.perf_counter()
                try:
                    result = client.chat(case["messages"], stream=True, max_tokens=OUTPUT_BUDGET,
                                         cache_salt=salt, response_format={"type": "json_object"})
                    passed, problem = check_answer(result.content, case["expected"])
                    finish = result.response["choices"][0]["finish_reason"]
                    row.update(success=True, quality_passed=passed and finish != "length",
                               quality_error=problem if finish != "length" else "Output truncated",
                               content=result.content, response=result.response, usage=result.usage,
                               elapsed_s=result.elapsed_s, ttft_s=result.ttft_s, tpot_s=result.tpot_s,
                               finish_reason=finish)
                except (ServiceError, ValueError, KeyError) as exc:
                    row.update(success=False, quality_passed=False,
                               elapsed_s=time.perf_counter() - call_started, error=str(exc))
                rows.append(row)
                stage_rows.append(row)
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                print(f"REQUEST trial={trial+1} condition={condition} case={case['id']} "
                      f"success={row['success']} quality={row['quality_passed']}", flush=True)
            wall = time.perf_counter() - started
            report["stages"].append({"trial": trial + 1, "wall_s": wall,
                                      **summarize(stage_rows)})
            persist()
    after = client.get_text("metrics", server_root=True)
    (directory / "server-metrics-after.txt").write_text(after, encoding="utf-8")
    boundaries.append({"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                       "stage": "after", "values": selected_metrics(after)})
    (directory / "metrics-boundaries.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in boundaries), encoding="utf-8")
    report["engine_metrics"] = boundary_metrics_summary(boundaries)
    report["counter_window_matches_24_requests"] = (
        report["engine_metrics"]["counter_deltas"]["request_prefill_kv_computed_tokens_count"] == len(rows))
    print("METRICS_REQUESTS=2 COUNTER_WINDOW_MATCHES_24=" + str(report["counter_window_matches_24_requests"]), flush=True)
    report["status"] = "complete"
    persist()
    print("RESULT_DIR=" + str(directory), flush=True)
    print("QUALITY_GATE=" + json.dumps({"sample_quality_gate_passed": report["sample_quality_gate_passed"],
                                        "measured_requests": len(rows)}), flush=True)
    if any(not r["success"] or not r["quality_passed"] for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
