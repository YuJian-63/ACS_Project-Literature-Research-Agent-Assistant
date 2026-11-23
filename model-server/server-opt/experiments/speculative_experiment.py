"""Prepare, bind and compare native N-gram speculation; never contact TACC."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

import gdn_experiment as gdn
import prefill_experiment as common

ROOT = Path(__file__).absolute().parent
PLAN = ROOT / "results/speculative-ngram-plan.json"
SERVE = ROOT / "qwen-private-serve"
CLIENT = ROOT / "qwen-private-serial-cache"
BASE = dict(common.BASE_CONFIG, profile="public-reference-gdn")
SPEC = {"method": "ngram_gpu", "num_speculative_tokens": 3,
        "prompt_lookup_min": 2, "prompt_lookup_max": 5}
OPTIONS = {"protocol": "serial-gdn-boundary-v2", "output_budget": 4096,
           "metrics_sampling": "experiment-boundaries"}


def settings(arm):
    return dict(BASE) if arm == "baseline" else dict(BASE, async_scheduling=True, speculative_config=dict(SPEC))


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def read_plan():
    return common.read_json(PLAN) if PLAN.exists() else {
        "experiment": "04-native-ngram-gpu", "kind": "existing-feature configuration trial",
        "runtime": "private", "status": "prepared_not_tacc_measured",
        "source_changes": False, "protocol_options": OPTIONS,
        "baseline_settings": settings("baseline"), "candidate_settings": settings("candidate"),
        "historical_public_reference_client": "30056",
        "baseline_client_job": "30056", "baseline_service_job": "30053",
        "baseline_directory": "results/job-30056", "async_scheduling": "enabled in both engines",
        "formal_reference": "Compare directly against the original public baseline 30056; do not substitute a synchronous rerun",
        "gdn_source_experiment": "Prior results and reviewed candidate archive retained; restore original private source before this trial to avoid stacking GDN changes",
        "mtp": "Not enabled. Course checkpoint metadata will be logged; usable MTP weights are not established",
    }


def select(arm):
    allowed = [dict(common.BASE_CONFIG, profile="public-reference-gdn"),
               settings("baseline"), settings("candidate")]
    current = common.read_json(SERVE / "service_config.json")
    common.require(current == common.read_json(CLIENT / "service_config.json"), "Server/client configs differ")
    common.require(current in allowed, "Unexpected active experiment; refusing to overwrite its settings")
    common.require(not (CLIENT / "storage-cleanup.json").exists(), "Remove the active cleanup plan first")
    if arm == "candidate":
        expected = gdn.manifest("baseline")
        if common.read_json(ROOT / "variant.json") != expected:
            common.require(current == BASE, "Restore the GDN baseline before enabling new speculative settings")
            gdn.select("baseline")
        common.require(common.read_json(ROOT / "vllm-src/csit6000v-variant.json") == expected,
                       "Source manifest is not the original private baseline")
        for name, digest in expected["source_sha256"].items():
            common.require(hashlib.sha256((ROOT / "vllm-src" / name).read_bytes()).hexdigest() == digest,
                           "Private source differs from its original baseline: " + name)
    plan = read_plan()
    write_json(SERVE / "service_config.json", settings(arm))
    write_json(CLIENT / "service_config.json", settings(arm))
    mode = "public" if arm == "baseline" else "private"
    (SERVE / "runtime-mode.txt").write_bytes((mode + "\n").encode())
    (CLIENT / "service-job-id.txt").write_bytes(b"UNSET\n")
    (CLIENT / "server-url.txt").write_bytes(b"http://NODE:8000/v1\n")
    (CLIENT / "measurement-mode.txt").write_bytes(b"short\n")
    plan.update(active_arm=arm, status=arm + "_deployment_prepared_not_tacc_measured")
    write_json(PLAN, plan)
    print("EXPERIMENT=04-native-ngram-gpu ARM=" + arm + " RUNTIME=" + mode + " ASYNC=true")
    if arm == "candidate":
        print("Build the restored original private source once to replace the previously installed GDN candidate.")
    print("Deploy the existing GPU task; after readiness, bind its downloaded log and submit the separate CPU task.")


def validate_service(text, report, arm):
    common.require(report["service_config"] == settings(arm), "Wrong arm's configuration")
    evidence = (common.public_service_evidence(text, report) if arm == "baseline"
                else common.service_evidence(text, report, source_manifest=gdn.manifest("baseline")))
    arguments = evidence["arguments"]
    actual = arguments.get("speculative_config")
    if isinstance(actual, str):
        actual = json.loads(actual)
    expected = settings(arm).get("speculative_config")
    common.require(actual == expected, "Actual speculative arguments differ from this arm")
    common.require(evidence["async_scheduling_enabled"] is True,
                   "Both arms must retain the original asynchronous scheduling")
    if arm == "candidate":
        common.require(json.loads(common.marker(text, "SPECULATIVE_CONFIG_REQUESTED")) == expected
                       and common.marker(text, "ASYNC_SCHEDULING_REQUESTED") == "true"
                       and arguments.get("async_scheduling") is True,
                       "Candidate must explicitly retain asynchronous scheduling")
        common.require("speculative_config=SpeculativeConfig(" in text
                       and re.search(r"method=['\"]ngram_gpu['\"]", text),
                       "Engine did not confirm the GPU N-gram speculative configuration")
    reference = common.read_json(SERVE / "source-reference.json")
    source = evidence["source_manifest"]
    common.require(source is not None
                   and all(source["source_sha256"].get(name) == digest
                           for name, digest in reference["source_sha256"].items())
                   and source["scheduler_sha256"] == reference["scheduler_sha256"],
                   "Need unchanged course runtime source evidence")
    support = None
    if arm == "candidate":
        support = json.loads(common.marker(text, "SPECULATIVE_RUNTIME_EVIDENCE"))
        common.require(len(support) == 7 and all(re.fullmatch(r"[0-9a-f]{64}", value)
                                               for value in support.values()),
                       "Missing native speculation implementation fingerprints")
    return evidence, support


def bind(arm, service_job_id, service_log):
    common.require(service_job_id.isdecimal(), "GPU job ID must be numeric")
    common.require(common.read_json(SERVE / "service_config.json") == settings(arm)
                   == common.read_json(CLIENT / "service_config.json")
                   and (SERVE / "runtime-mode.txt").read_text().strip() == ("public" if arm == "baseline" else "private"),
                   "Select this arm before binding")
    text = Path(service_log).read_text(encoding="utf-8-sig")
    report = {"service_job_id": service_job_id, "service_config": settings(arm),
              "base_url": common.marker(text, "SERVICE_BASE_URL")}
    evidence, support = validate_service(text, report, arm)
    (CLIENT / "service-job-id.txt").write_bytes((service_job_id + "\n").encode())
    (CLIENT / "server-url.txt").write_bytes((report["base_url"] + "\n").encode())
    plan = read_plan()
    plan[arm + "_service"] = {"job_id": service_job_id, "base_url": report["base_url"],
                              "log_sha256": hashlib.sha256(Path(service_log).read_bytes()).hexdigest(),
                              "runtime_versions": evidence["runtime_versions"], "support_hashes": support}
    plan["status"] = arm + "_ready_cpu_not_submitted_by_assistant"
    write_json(PLAN, plan)
    print("BOUND_GPU_JOB=" + service_job_id + " ARM=" + arm + " URL=" + report["base_url"])
    print("Submit the existing qwen-private-serial-cache CPU task separately.")


def compare(baseline, candidate):
    runs, supports = [], []
    for arm, directory in (("baseline", baseline), ("candidate", candidate)):
        run = common.load_run(directory, 4096, settings=settings(arm),
                              service_kind="public" if arm == "baseline" else "private",
                              source_manifest=None if arm == "baseline" else gdn.manifest("baseline"),
                              protocol_options=OPTIONS)
        text = (Path(directory) / "service.log").read_text(encoding="utf-8-sig")
        _, support = validate_service(text, run["report"], arm)
        runs.append(run)
        supports.append(support)
    common.require(runs[0]["service"]["execution"] == runs[1]["service"]["execution"],
                   "Model execution backends differ")
    common.require(str(runs[0]["report"]["client_job_id"]) == "30056"
                   and str(runs[0]["report"]["service_job_id"]) == "30053",
                   "Use the original public baseline CPU30056/GPU30053")
    result = common.compare_runs(*runs, varying_parameter="speculative_config")
    result["experiment"] = "04-native-ngram-gpu"
    result["source_code_speedup_claim"] = False
    counters = speculation_deltas(Path(candidate))
    drafts = counters["spec_decode_num_drafts_total"]
    proposed = counters["spec_decode_num_draft_tokens_total"]
    accepted = counters["spec_decode_num_accepted_tokens_total"]
    result["speculation"] = {
        "num_drafts": drafts, "proposed_tokens": proposed, "accepted_tokens": accepted,
        "acceptance_rate": accepted / proposed if accepted is not None and proposed else None,
        "mean_accepted_draft_tokens_per_draft": accepted / drafts if accepted is not None and drafts else None,
        "activity_observed": drafts is not None and drafts > 0,
        "scope": "Two boundary snapshots only; missing counters are unknown, not zero. Request counts do not independently prove speculative statistics cover exactly the same 24 requests",
        "spec_counter_window_matches_24_independently_verified": False,
        "counter_deltas": counters,
    }
    result["speculation_implementation_fingerprints"] = supports[1]
    result["original_baseline_has_speculation_fingerprints"] = supports[0] is not None
    result["notes"].extend([
        "Formal comparison retains the original public baseline 30056 and asynchronous scheduling. Do not replace it with a synchronous control.",
        "Public baseline versus private original source with native GPU N-gram; known model source hashes and runtime versions are checked, complete installation identity and node equivalence are not established.",
        "Native feature/configuration experiment; no new decoding algorithm or vLLM source change.",
        "Short JSON screening does not establish long-output or real Agent performance.",
        "Inspect output-token differences and physical GPU/node differences before attributing elapsed-time changes.",
    ])
    return result


def speculation_deltas(directory):
    names = ("spec_decode_num_drafts_total", "spec_decode_num_draft_tokens_total",
             "spec_decode_num_accepted_tokens_total", "spec_decode_num_accepted_tokens_per_pos_total")
    snapshots = []
    for stage in ("before", "after"):
        values = {}
        for line in (directory / ("server-metrics-" + stage + ".txt")).read_text().splitlines():
            match = re.fullmatch(r"vllm:(\w+)(\{.*\})?\s+(\S+)(?:\s+\S+)?", line)
            if match and match[1] in names:
                value = float(match[3])
                common.require(math.isfinite(value), "Invalid speculative counter")
                values.setdefault(match[1], {})[match[2] or ""] = value
        snapshots.append(values)
    deltas = dict.fromkeys(names)
    for name in names:
        before, after = (snapshot.get(name, {}) for snapshot in snapshots)
        if before and before.keys() == after.keys() and all(after[key] >= before[key] for key in before):
            deltas[name] = sum(after[key] - before[key] for key in before)
    return deltas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selector = commands.add_parser("select")
    selector.add_argument("arm", choices=("baseline", "candidate"))
    binder = commands.add_parser("bind")
    binder.add_argument("arm", choices=("baseline", "candidate"))
    binder.add_argument("--service-job-id", required=True)
    binder.add_argument("--service-log", type=Path, required=True)
    comparator = commands.add_parser("compare")
    comparator.add_argument("baseline", type=Path)
    comparator.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "select":
            select(args.arm)
        elif args.command == "bind":
            bind(args.arm, args.service_job_id, args.service_log)
        else:
            result = compare(args.baseline, args.candidate)
            output = ROOT / "results" / ("speculative-comparison-" + result["runs"][0]["client_job_id"]
                                         + "-" + result["runs"][1]["client_job_id"] + ".json")
            write_json(output, result)
            plan = read_plan()
            plan.update(status="paired_runs_evaluated", comparison=str(output.relative_to(ROOT)))
            write_json(PLAN, plan)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print("COMPARISON=" + str(output))
    except (ValueError, KeyError, FileNotFoundError) as exc:
        parser.exit(2, "ERROR: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
