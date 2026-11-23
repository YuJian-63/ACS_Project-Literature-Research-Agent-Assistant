"""Select and compare the private-baseline 4096/8192 prefill experiment locally."""

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT / "qwen-private-serial-cache"))
from cache_quality import ServiceError, check_answer, prefix_caching_from_metrics
from metrics_sampler import (
    COUNTERS,
    boundary_metrics_summary,
    metrics_summary,
    selected_metrics,
)

SCHEDULER_SHA256 = "2ed2a550b6558b2495eda845a97ae38bcf0225027b9e25fbf00fc3880c1d3941"
WORKLOAD_SHA256 = "2507b977f459d8075abca7c622c8770f2c336d5bc6c2b42a0b37c7a7e609dd9d"
PROTOCOL = "serial-prefill-budget-v1"
BASE_CONFIG = {
    "profile": "private-serial-latency", "max_model_len": 36864,
    "max_num_seqs": 4, "max_num_batched_tokens": 4096,
    "gpu_memory_utilization": 0.9, "enable_prefix_caching": True,
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_config(budget):
    return dict(BASE_CONFIG, max_num_batched_tokens=budget)


def select(arm):
    variant = read_json(ROOT / "variant.json")
    scheduler = ROOT / "vllm-src/vllm/v1/core/sched/scheduler.py"
    require(variant["variant"] == "baseline"
            and hashlib.sha256(scheduler.read_bytes()).hexdigest() == SCHEDULER_SHA256,
            "Experiment 1 requires the unchanged private baseline source")
    server = ROOT / "qwen-private-serve/service_config.json"
    client = ROOT / "qwen-private-serial-cache"
    current = read_json(server)
    require(current == read_json(client / "service_config.json"), "Server/client configs differ")
    require(current in (expected_config(4096), expected_config(8192)),
            "Unexpected settings; refusing to overwrite another experiment's configuration")
    require(not (client / "storage-cleanup.json").exists(), "Remove the active cleanup plan first")
    budget = 4096 if arm == "baseline" else 8192
    contents = (json.dumps(expected_config(budget), indent=2) + "\n").encode("utf-8")
    server.write_bytes(contents)
    (client / "service_config.json").write_bytes(contents)
    (client / "service-job-id.txt").write_bytes(b"UNSET\n")
    (client / "server-url.txt").write_bytes(b"http://NODE:8000/v1\n")
    print(f"EXPERIMENT=prefill-budget ARM={arm} BUDGET={budget} APC=true SOURCE=baseline")
    print("Deploy the GPU service, wait for readiness, then fill its new job ID/URL and submit the CPU client.")


def marker(text, name):
    matches = re.findall(r"^" + re.escape(name) + r"=(.+)$", text, flags=re.MULTILINE)
    require(len(matches) == 1, f"Expected one {name} in service.log")
    return matches[0].strip()


def execution_evidence(text):
    patterns = {
        "architecture": r"Resolved architecture:\s*(\w+)",
        "quantization": r"\bquantization=([^,]+)",
        "attention_backend": r"Using (\w+) attention backend",
        "gdn_backend": r"Using (.+?) GDN prefill kernel",
        "linear_kernel": r"Using (\w+LinearKernel) for",
    }
    return {name: match.group(1).strip("'\"") if (match := re.search(pattern, text)) else None
            for name, pattern in patterns.items()}


def public_service_evidence(text, report):
    require("Application startup complete." in text, "Public service.log does not show readiness")
    require("PRIVATE VLLM / PUBLIC DEPENDENCIES CHECK PASSED" not in text,
            "Expected the public reference, not a private service")
    require(marker(text, "STOP_SERVICE_WITH") == "tcloud cancel -j " + str(report["service_job_id"]),
            "Wrong public GPU job log")
    require(marker(text, "SERVICE_BASE_URL").rstrip("/") == report["base_url"].rstrip("/"),
            "Client URL and public GPU log differ")
    rows = re.findall(r"non-default args: (\{[^\r\n]+\})", text)
    require(len(rows) == 1, "Need unique public startup arguments")
    arguments = ast.literal_eval(rows[0])
    require("/course-envs/CSIT6000V/project/" in arguments.get("model", ""),
            "Public model must use the recorded course public environment")
    for key in ("max_model_len", "max_num_seqs", "max_num_batched_tokens",
                "gpu_memory_utilization", "enable_prefix_caching"):
        require(arguments.get(key) == report["service_config"][key],
                "Actual public server argument differs: " + key)
    require(arguments.get("tensor_parallel_size") == 2 and arguments.get("dtype") == "bfloat16",
            "Public TP or compute dtype differs")
    require("enable_prefix_caching=True" in text, "Public engine did not confirm APC")
    version = re.search(r"Initializing a V1 LLM engine \(v([^\)]+)\)", text)
    require(version is not None, "Missing public vLLM version")
    wrapped = "PUBLIC VLLM / PUBLIC DEPENDENCIES CHECK PASSED" in text
    versions = {"vllm": version[1], "torch": None, "transformers": None, "triton": None}
    source = None
    if wrapped:
        require(marker(text, "RUNTIME_MODE") == "public", "Wrong public runtime selection")
        require(json.loads(marker(text, "PUBLIC_SERVICE_CONFIG")) == report["service_config"],
                "Public wrapper/client configurations differ")
        versions = json.loads(marker(text, "RUNTIME_VERSIONS"))
        require(versions["vllm"] == version[1], "Public runtime version differs from engine")
        source = json.loads(marker(text, "PUBLIC_SOURCE_EVIDENCE"))
        require(source["source_sha256"] == json.loads(marker(text, "SOURCE_SHA256")),
                "Public source hash records differ")
        require(source["scheduler_sha256"] == marker(text, "SCHEDULER_SHA256"),
                "Public scheduler hash records differ")
    gpus = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(("index, uuid, memory.free", "index, name, uuid, memory.total")):
            for fields in csv.reader(lines[index + 1:index + 3], skipinitialspace=True):
                require(len(fields) in (4, 5), "Unexpected public GPU inventory")
                named = len(fields) == 5
                gpus.append({"name": fields[1] if named else None,
                             "uuid": fields[2] if named else fields[1],
                             "free_mib_at_start": int(fields[4 if named else 2].split()[0]),
                             "total_mib": int(fields[3].split()[0])})
            break
    require(len(gpus) == 2, "Missing public two-GPU inventory")
    nodes = re.findall(r"^(\d+-\d+-\d+-\d+)\s*$", text, re.MULTILINE)
    capacities = set(re.findall(r"GPU KV cache size:\s*([\d,]+) tokens", text))
    return {
        "source_kind": "public", "arguments": arguments,
        "runtime_versions": versions,
        "gpus": gpus, "node": nodes[0] if nodes else None,
        "custom_allreduce_disabled": "Custom allreduce is disabled" in text,
        "async_scheduling_enabled": "Asynchronous scheduling is enabled." in text,
        "startup_memory_profile_by_tp_rank": {}, "reported_kv_budget_gib_by_tp_rank": {},
        "reported_gpu_budget_gib_by_tp_rank": {},
        "reported_kv_token_capacity": int(next(iter(capacities)).replace(",", ""))
        if len(capacities) == 1 else None,
        "source_manifest": source, "execution": execution_evidence(text),
        "provenance_limitations": "Targeted source hashes recorded; complete installation and weight equivalence not established"
        if wrapped else "Public log has no source hashes, dependency versions or GPU model names",
    }


def service_evidence(text, report, source_manifest=None):
    require("Application startup complete." in text, "service.log does not show readiness")
    require("PRIVATE VLLM / PUBLIC DEPENDENCIES CHECK PASSED" in text,
            "Expected a private service log, not a public reference")
    require(marker(text, "SERVICE_JOB_ID") == str(report["service_job_id"]), "Wrong GPU job log")
    require(marker(text, "SERVICE_BASE_URL").rstrip("/") == report["base_url"].rstrip("/"),
            "Client URL and GPU service log differ")
    require(marker(text, "SCHEDULER_SHA256") == SCHEDULER_SHA256, "Wrong running scheduler")
    source = json.loads(marker(text, "PRIVATE_SOURCE_VARIANT"))
    if source_manifest is None:
        require(source["variant"] == "baseline",
                "A source candidate was mixed into the parameter experiment")
    else:
        require(source == source_manifest, "Running source manifest differs from selected arm")
        require(json.loads(marker(text, "SOURCE_SHA256")) == source_manifest["source_sha256"],
                "Missing or mismatched running source-file hashes")
        require("Using Triton/FLA GDN prefill kernel" in text,
                "Both source arms must use the same Triton/FLA GDN backend")
        if source_manifest["variant"] == "gdn-indexed-state":
            require(marker(text, "GDN_KERNEL_CHECK_PASSED") == "2",
                    "Need successful real-kernel checks on both allocated GPUs")
            require("GDN indexed-state prefill read enabled." in text,
                    "The model did not confirm using the indexed-state path")
    config = report["service_config"]
    require(json.loads(marker(text, "PRIVATE_SERVICE_CONFIG")) == config, "GPU/client configs differ")
    args_lines = re.findall(r"non-default args: (\{[^\r\n]+\})", text)
    require(len(args_lines) == 1, "Cannot identify unique actual vLLM startup arguments")
    arguments = ast.literal_eval(args_lines[0])
    for key in ("max_model_len", "max_num_seqs", "max_num_batched_tokens",
                "gpu_memory_utilization", "enable_prefix_caching"):
        require(arguments.get(key) == config[key], f"Actual server argument differs: {key}")
    require(arguments.get("tensor_parallel_size") == 2 and arguments.get("dtype") == "bfloat16",
            "Unexpected TP or compute dtype")
    require("enable_prefix_caching=True" in text, "Engine did not confirm APC enabled")
    versions = json.loads(marker(text, "RUNTIME_VERSIONS"))
    lines = text.splitlines()
    gpu_rows = []
    for index, line in enumerate(lines):
        if line.strip().startswith("index, name, uuid, memory.total"):
            for fields in csv.reader(lines[index + 1:index + 3], skipinitialspace=True):
                require(len(fields) == 5, "Unexpected GPU inventory format")
                gpu_rows.append({"name": fields[1], "uuid": fields[2],
                                 "total_mib": int(fields[3].split()[0]),
                                 "free_mib_at_start": int(fields[4].split()[0])})
            break
    require(len(gpu_rows) == 2, "Missing two-GPU inventory in service.log")
    nodes = re.findall(r"^(\d+-\d+-\d+-\d+)\s*$", text, flags=re.MULTILINE)
    memory = {}
    pattern = (r"\(Worker_TP(\d+)[^\n]*?Actual usage is ([\d.]+) GiB for weight, "
               r"([\d.]+) GiB for peak activation, ([\d.]+) GiB for non-torch memory, "
               r"and ([\d.]+) GiB for CUDAGraph memory")
    for match in re.finditer(pattern, text):
        memory[match[1]] = dict(zip(
            ("weight_gib", "profile_peak_activation_gib", "non_torch_gib", "cuda_graph_gib"),
            map(float, match.groups()[1:]),
        ))
    kv_budgets = {
        match[1]: float(match[2]) for match in re.finditer(
            r"\(Worker_TP(\d+)[^\r\n]*Current kv cache memory in use is ([\d.]+) GiB", text)
    }
    gpu_budgets = {
        match[1]: float(match[2]) for match in re.finditer(
            r"\(Worker_TP(\d+)[^\r\n]*Desired GPU memory utilization is \([\d.]+, ([\d.]+) GiB\)", text)
    }
    capacities = set(re.findall(r"GPU KV cache size:\s*([\d,]+) tokens", text))
    return {"arguments": arguments, "runtime_versions": versions, "gpus": gpu_rows, "node": nodes[0] if nodes else None,
            "custom_allreduce_disabled": "Custom allreduce is disabled" in text,
            "async_scheduling_enabled": "Asynchronous scheduling is enabled." in text,
            "startup_memory_profile_by_tp_rank": memory,
            "reported_kv_budget_gib_by_tp_rank": kv_budgets,
            "reported_gpu_budget_gib_by_tp_rank": gpu_budgets,
            "reported_kv_token_capacity": int(next(iter(capacities)).replace(",", ""))
            if len(capacities) == 1 else None, "source_manifest": source,
            "source_kind": "private", "execution": execution_evidence(text)}


def load_run(directory, budget, settings=None, source_manifest=None, service_kind="private", protocol_options=None):
    directory = Path(directory)
    report = read_json(directory / "summary.json")
    options = protocol_options or {"protocol": PROTOCOL, "output_budget": 256, "metrics_sampling": "periodic"}
    require(report.get("protocol") == options["protocol"] and report.get("status") == "complete",
            "Need a complete new-protocol run; job-29878 uses a different protocol")
    require(report.get("sample_quality_gate_passed") is True, "Client quality gate failed")
    require(report.get("service_config") == (settings if settings is not None else expected_config(budget)),
            "Unexpected service configuration")
    require(read_json(directory / "service_config.json") == report["service_config"],
            "Downloaded config differs from summary")
    require(report.get("prefix_caching_enabled") is True and report.get("concurrency") == 1,
            "Both runs must be serial with APC enabled")
    require((report.get("trials"), report.get("cases_per_trial"), report.get("output_budget")) == (4, 6, options["output_budget"]),
            "Changed trial count, question count or output budget")
    require(report.get("temperature") == 0 and report.get("thinking") is False
            and report.get("natural_eos") is True and report.get("first_question_included") is True,
            "Changed sampling or measurement rules")
    require(report.get("warmup_requests") == options.get("warmup_requests", 2)
            and report.get("warmup_target_document_requests") == options.get("warmup_target_document_requests", 1),
            "Different warmup protocol")
    warmup = read_json(directory / "warmup.json")
    require(warmup.get("measured") is False, "Warmup must be outside measurement")
    if options.get("warmup_quality_required", True):
        require(warmup.get("quality_passed") is True, "Missing successful unmeasured warmup")
    else:
        require(warmup.get("quality_policy") == "record-only"
                and report.get("warmup_quality_policy", "").startswith("record-only"),
                "Missing explicit diagnostic-only warmup policy")
    require(prefix_caching_from_metrics((directory / "server-metrics-before.txt").read_text()) is True,
            "Server metrics did not confirm APC enabled")
    boundary = options["metrics_sampling"] == "experiment-boundaries"
    if boundary:
        require(report.get("metrics_sampling") == "experiment-boundaries" and report.get("metrics_requests") == 2,
                "Boundary protocol requires exactly two metrics requests")
        require(report.get("max_input_tokens") == 32767, "Wrong Agent input limit")
    cases = read_json(directory / "workload.json")
    workload_hash = hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()
    require(workload_hash == options.get("workload_sha256", WORKLOAD_SHA256) == report.get("workload_sha256"), "Workload changed")
    rows = [json.loads(line) for line in (directory / "answers.jsonl").read_text(encoding="utf-8").splitlines() if line]
    require(len(rows) == 24, "Expected exactly 24 measured responses")
    for index, row in enumerate(rows):
        case = cases[index % 6]
        require((row.get("trial"), row.get("position"), row.get("case_id"))
                == (index // 6 + 1, index % 6, case["id"]), "Changed request order")
        require(row.get("success") is True and row.get("quality_passed") is True
                and row.get("finish_reason") not in (None, "length")
                and check_answer(row.get("content", ""), case["expected"])[0],
                f"Independent quality check failed: trial={row.get('trial')} case={case['id']}")
        for metric in ("elapsed_s", "ttft_s", "tpot_s"):
            value = row.get(metric)
            require((value is None and metric == "tpot_s") or
                    (type(value) in (int, float) and math.isfinite(value) and value >= 0),
                    f"Invalid latency measurement: {metric}")
        require(row["elapsed_s"] >= row["ttft_s"], "TTFT exceeds complete request time")
        for metric in ("prompt_tokens", "completion_tokens"):
            require(type(row["usage"].get(metric)) is int and row["usage"][metric] > 0,
                    "Missing actual token counts")
        if boundary:
            require(row["usage"]["prompt_tokens"] <= 32767 and row["usage"]["completion_tokens"] <= 4096,
                    "Response exceeds Agent limits")
    stages = report.get("stages", [])
    require(len(stages) == 4 and [s["trial"] for s in stages] == [1, 2, 3, 4], "Missing trial timings")
    for stage in stages:
        require(type(stage.get("wall_s")) in (int, float) and math.isfinite(stage["wall_s"])
                and stage["wall_s"] > 0, "Invalid workflow timing")
    if boundary:
        samples = [json.loads(line) for line in (directory / "metrics-boundaries.jsonl").read_text().splitlines() if line]
        require(len(samples) == 2 and [s.get("stage") for s in samples] == ["before", "after"],
                "Need exactly the before/after counter snapshots")
        require(prefix_caching_from_metrics((directory / "server-metrics-after.txt").read_text()) is True,
                "Final server metrics did not confirm APC")
        for sample, filename in zip(samples, ("server-metrics-before.txt", "server-metrics-after.txt")):
            require(sample.get("values") == selected_metrics((directory / filename).read_text()),
                    "Boundary snapshot differs from raw server metrics")
        observed = [boundary_metrics_summary(samples)]
    else:
        observed = [metrics_summary([json.loads(line) for line in
                    (directory / f"metrics-trial-{trial}.jsonl").read_text().splitlines() if line])
                    for trial in range(1, 5)]
    require(service_kind in ("private", "public"), "Unknown service source kind")
    text = (directory / "service.log").read_text(encoding="utf-8-sig")
    evidence = public_service_evidence(text, report) if service_kind == "public" else service_evidence(
        text, report, source_manifest=source_manifest)
    return {"path": str(directory), "report": report, "rows": rows, "observed": observed, "service": evidence}


def pair(baseline, candidate):
    return {"baseline": baseline, "candidate": candidate,
            "reduction_fraction": 1 - candidate / baseline
            if baseline is not None and baseline > 0 and candidate is not None else None}


def counter_total(run, metric):
    values = [stage["counter_deltas"].get(metric) for stage in run["observed"]]
    return sum(values) if all(value is not None for value in values) else None


def compare_runs(baseline, candidate, varying_parameter="max_num_batched_tokens"):
    require(varying_parameter in ("max_num_batched_tokens", "gpu_memory_utilization", "source", "public_source_reference", "speculative_config"),
            "Unsupported experiment variable")
    before, after = baseline["report"], candidate["report"]
    for key in ("model", "input_token_counts", "measurement_code_sha256", "cache_isolation", "protocol", "output_budget"):
        require(before.get(key) is not None and before.get(key) == after.get(key), f"Mismatch: {key}")
    arguments_a = dict(baseline["service"]["arguments"])
    arguments_b = dict(candidate["service"]["arguments"])
    public_reference = varying_parameter == "public_source_reference"
    deployment_differences = {}
    if public_reference:
        keys = set(arguments_a) | set(arguments_b)
        deployment_differences = {key: {"baseline": arguments_a.get(key), "candidate": arguments_b.get(key)}
                                  for key in keys if arguments_a.get(key) != arguments_b.get(key)}
        allowed = {"model", "enable_auto_tool_choice", "tool_call_parser", "disable_access_log_for_endpoints"}
        require(set(deployment_differences) <= allowed,
                "Unmatched public/candidate model settings: " + str(set(deployment_differences) - allowed))
        require(Path(arguments_a["model"]).name == Path(arguments_b["model"]).name,
                "Different model checkpoint identifiers")
        for key in allowed:
            arguments_a.pop(key, None)
            arguments_b.pop(key, None)
    elif varying_parameter == "speculative_config":
        arguments_a.pop(varying_parameter, None)
        arguments_b.pop(varying_parameter, None)
        require(baseline["service"].get("async_scheduling_enabled") is True
                and candidate["service"].get("async_scheduling_enabled") is True,
                "Both engines must confirm asynchronous scheduling")
        arguments_a.pop("async_scheduling", None)
        arguments_b.pop("async_scheduling", None)
        if baseline["service"]["source_kind"] != candidate["service"]["source_kind"]:
            require(Path(arguments_a["model"]).name == Path(arguments_b["model"]).name,
                    "Different model checkpoint identifiers")
            deployment_differences["model"] = {"baseline": arguments_a.pop("model"),
                                               "candidate": arguments_b.pop("model")}
    elif varying_parameter != "source":
        del arguments_a[varying_parameter]
        del arguments_b[varying_parameter]
    require(arguments_a == arguments_b, "Actual vLLM arguments changed beyond " + varying_parameter)
    if public_reference:
        for key, value in baseline["service"]["runtime_versions"].items():
            if value is not None:
                require(value == candidate["service"]["runtime_versions"].get(key),
                        "Different known runtime version: " + key)
        for key, value in baseline["service"]["execution"].items():
            require(value is not None and value == candidate["service"]["execution"].get(key),
                    "Different or missing execution evidence: " + key)
    else:
        require(baseline["service"]["runtime_versions"] == candidate["service"]["runtime_versions"],
                "Different vLLM/Torch/Transformers/Triton versions")
    hardware = lambda run: sorted((g["name"], g["total_mib"]) for g in run["service"]["gpus"])
    if public_reference:
        if all(g["name"] is not None for run in (baseline, candidate) for g in run["service"]["gpus"]):
            require(hardware(baseline) == hardware(candidate), "Different GPU hardware")
        require(sorted(g["total_mib"] for g in baseline["service"]["gpus"])
                == sorted(g["total_mib"] for g in candidate["service"]["gpus"]),
                "Different GPU memory capacities")
    else:
        require(hardware(baseline) == hardware(candidate), "Different GPU hardware")
    require(baseline["service"]["custom_allreduce_disabled"] == candidate["service"]["custom_allreduce_disabled"],
            "Different communication fallback")
    latencies = {}
    cold_positions = before.get("cold_question_positions", [0])
    require(cold_positions == after.get("cold_question_positions", [0]), "Different cold-request grouping")
    groups = {"all_requests": lambda r: True, "first_questions": lambda r: r["position"] in cold_positions,
              "following_questions": lambda r: r["position"] not in cold_positions}
    for group, predicate in groups.items():
        latencies[group] = {}
        for metric in ("ttft_s", "elapsed_s", "tpot_s"):
            values = [[row[metric] for row in run["rows"] if predicate(row) and row[metric] is not None]
                      for run in (baseline, candidate)]
            latencies[group][metric] = {
                "mean": pair(*(statistics.mean(v) if v else None for v in values)),
                "median": pair(*(statistics.median(v) if v else None for v in values)),
                "sample_counts": [len(v) for v in values],
            }
    counters = [{name: counter_total(run, name) for name in COUNTERS} for run in (baseline, candidate)]
    hits = []
    for totals in counters:
        h, q = totals["prefix_cache_hits_total"], totals["prefix_cache_queries_total"]
        hits.append(h / q if h is not None and q else None)
    notes = ["One deployment per arm is preliminary screening; repeat promising results in alternating order.",
             "Startup/JIT time is not request TTFT. Initial article-processing cost is included in every measured trial.",
             "Counter snapshots can lag requests; incomplete counter windows cannot prove compute savings.",
             "Startup activation profiles are not measured inference GPU-memory peaks; no whole-service CPU/energy claim."]
    if public_reference:
        notes.append("Public-to-private deployment comparison: inspect recorded runtime versions, hardware and targeted source evidence; complete installation/weight equivalence is not established, so the isolated patch contribution is not proven.")
    if before.get("metrics_sampling") == "experiment-boundaries":
        notes.append("Only two /metrics reads outside timing; no KV/queue peaks. Counter differences may lag or include other traffic; use the request-count window check before making resource claims.")
    if baseline["service"]["node"] != candidate["service"]["node"]:
        notes.append("Different GPU nodes: node load, CPU and network effects remain possible confounders.")
    if before.get("client_host") != after.get("client_host"):
        notes.append("Different CPU client hosts: client-side latency may include different network/CPU overhead.")
    output_tokens = [sum(row["usage"]["completion_tokens"] for row in run["rows"]) for run in (baseline, candidate)]
    if output_tokens[0] != output_tokens[1]:
        notes.append("Completion-token totals differ; read TPOT and quality alongside total elapsed time.")
    return {
        "experiment": "prefill-budget-4096-vs-8192" if varying_parameter == "max_num_batched_tokens"
        else "gdn-public-reference" if public_reference
        else "gdn-indexed-state" if varying_parameter == "source"
        else "kv-memory-fraction-0.9-vs-0.6",
        "varying_parameter": varying_parameter,
        "kind": "public_baseline_comparison" if public_reference else
        "source_change" if varying_parameter == "source" else "parameter_tuning",
        "isolated_source_gain_attribution_verified": False,
        "deployment_argument_differences": deployment_differences,
        "quality_gate_passed": True,
        "scope": "Fixed synthetic sample only; not a general quality guarantee"
        if varying_parameter in ("source", "public_source_reference") else
        "Fixed synthetic sample only; not a source-code speedup or a general quality guarantee",
        "runs": [{"result_directory": run["path"], "client_job_id": run["report"]["client_job_id"],
                  "client_host": run["report"].get("client_host"),
                  "service_job_id": run["report"]["service_job_id"], "config": run["report"]["service_config"],
                  "service_evidence": run["service"]} for run in (baseline, candidate)],
        "quality": {"baseline": "24/24 independently checked", "candidate": "24/24 independently checked"},
        "latencies": latencies,
        "mean_six_question_workflow_s": pair(*(statistics.mean(s["wall_s"] for s in run["report"]["stages"])
                                               for run in (baseline, candidate))),
        "workflow_trials_s": [[s["wall_s"] for s in run["report"]["stages"]] for run in (baseline, candidate)],
        "completion_tokens": {"baseline": output_tokens[0], "candidate": output_tokens[1]},
        "observed_engine_counters": {"baseline": counters[0], "candidate": counters[1]},
        "prefill_counter_count_matches_expected_24": [c["request_prefill_kv_computed_tokens_count"] == 24 for c in counters],
        "observed_token_cache_hit_fraction": {"baseline": hits[0], "candidate": hits[1],
                                              "change_percentage_points": 100 * (hits[1] - hits[0])
                                              if all(h is not None for h in hits) else None},
        "notes": notes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selector = commands.add_parser("select")
    selector.add_argument("arm", choices=("baseline", "candidate"))
    comparator = commands.add_parser("compare")
    comparator.add_argument("baseline", type=Path)
    comparator.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "select":
            select(args.arm)
            return
        baseline, candidate = load_run(args.baseline, 4096), load_run(args.candidate, 8192)
        require(baseline["report"]["client_job_id"] != candidate["report"]["client_job_id"], "Need different CPU jobs")
        comparison = compare_runs(baseline, candidate)
        ids = [str(run["report"]["client_job_id"]) for run in (baseline, candidate)]
        require(all(re.fullmatch(r"\d+", value) for value in ids), "Invalid result job ID")
        target = ROOT / "results" / f"prefill-comparison-{ids[0]}-{ids[1]}.json"
        target.write_bytes((json.dumps(comparison, indent=2) + "\n").encode("utf-8"))
        print("COMPARISON_FILE=" + str(target))
        print(json.dumps({"quality_gate_passed": True,
                          "first_question_ttft_s": comparison["latencies"]["first_questions"]["ttft_s"]["mean"],
                          "mean_workflow_s": comparison["mean_six_question_workflow_s"]}, indent=2))
    except (ValueError, OSError, KeyError, TypeError, ServiceError) as exc:
        parser.exit(1, "Experiment validation failed; no speedup claim: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
