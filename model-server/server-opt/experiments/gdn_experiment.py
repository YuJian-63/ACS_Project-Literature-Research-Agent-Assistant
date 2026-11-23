"""Select and compare the GDN indexed-state source experiment in this directory."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import prefill_experiment as common

ROOT = Path(__file__).absolute().parent
PLAN = ROOT / "results/gdn-indexed-state-plan.json"
BUNDLE = ROOT / "backups/gdn-indexed-state-sources.zip"
RUNTIME_FILES = (
    "vllm/third_party/flash_linear_attention/ops/chunk.py",
    "vllm/third_party/flash_linear_attention/ops/chunk_delta_h.py",
    "vllm/model_executor/layers/mamba/gdn/qwen_gdn_linear_attn.py",
)


def manifest(arm):
    return common.read_json(PLAN)["manifests"][arm]


def settings():
    return common.read_json(PLAN).get("comparison_settings", common.BASE_CONFIG)


def use_public_baseline(service_job_id, service_log):
    text = Path(service_log).read_text(encoding="utf-8-sig")
    config = dict(common.BASE_CONFIG, profile="public-reference-gdn", max_model_len=36864)
    report = {"service_job_id": str(service_job_id),
              "base_url": common.marker(text, "SERVICE_BASE_URL"), "service_config": config}
    evidence = common.public_service_evidence(text, report)
    client = ROOT / "qwen-private-serial-cache"
    common.require(not (client / "storage-cleanup.json").exists(), "Remove the active cleanup plan first")
    expected_execution = {"architecture": "Qwen3_5ForConditionalGeneration",
                          "quantization": "compressed-tensors", "attention_backend": "FLASH_ATTN",
                          "gdn_backend": "Triton/FLA", "linear_kernel": "MarlinLinearKernel"}
    common.require(evidence["execution"] == expected_execution, "Public execution backends differ from this experiment")
    contents = (json.dumps(config, indent=2) + "\n").encode()
    for path in (ROOT / "qwen-private-serve/service_config.json", client / "service_config.json"):
        path.write_bytes(contents)
    (client / "service-job-id.txt").write_bytes((str(service_job_id) + "\n").encode())
    (client / "server-url.txt").write_bytes((report["base_url"] + "\n").encode())
    plan = common.read_json(PLAN)
    plan.update(baseline_kind="public", baseline_service_job=str(service_job_id),
                baseline_client_job=None, comparison_settings=config,
                public_baseline_evidence=evidence, public_baseline_log=str(Path(service_log).absolute()),
                status="public_baseline_client_prepared", source_gain_attribution_verified=False)
    PLAN.write_bytes((json.dumps(plan, indent=2) + "\n").encode())
    print("PUBLIC_BASELINE_SERVICE=" + str(service_job_id) + " URL=" + report["base_url"])
    print("CONFIG=CONTEXT36864/PREFILL4096/GPU0.9/APC-on; input32767/output4096")
    print("Submit the existing independent CPU client; no public rebuild or redeployment needed.")


def select(arm):
    plan = common.read_json(PLAN)
    if arm == "public-baseline":
        common.require(settings()["max_model_len"] == 36864, "Agent limits require context36864")
        for folder in ("qwen-private-serve", "qwen-private-serial-cache"):
            common.require(common.read_json(ROOT / folder / "service_config.json") == settings(),
                           "Server/client settings must match the full-context experiment")
        common.require(not (ROOT / "qwen-private-serial-cache/storage-cleanup.json").exists(),
                       "Remove the active cleanup plan first")
        (ROOT / "qwen-private-serve/runtime-mode.txt").write_bytes(b"public\n")
        (ROOT / "qwen-private-serial-cache/measurement-mode.txt").write_bytes(b"short\n")
        for name, contents in (("service-job-id.txt", b"UNSET\n"), ("server-url.txt", b"http://NODE:8000/v1\n")):
            (ROOT / "qwen-private-serial-cache" / name).write_bytes(contents)
        plan.update(active_runtime="public", baseline_kind="public", status="public36864_deployment_prepared")
        PLAN.write_bytes((json.dumps(plan, indent=2) + "\n").encode())
        print("RUNTIME_MODE=public CONTEXT=36864; submit existing qwen-private-serve, no build needed")
        return
    source_root = ROOT / "vllm-src"
    scheduler = source_root / "vllm/v1/core/sched/scheduler.py"
    common.require(
        hashlib.sha256(scheduler.read_bytes()).hexdigest() == common.SCHEDULER_SHA256,
        "Restore the original scheduler before this experiment",
    )
    client = ROOT / "qwen-private-serial-cache"
    for path in (
        client / "service_config.json",
        ROOT / "qwen-private-serve/service_config.json",
    ):
        common.require(
            common.read_json(path) == settings(),
            "This experiment requires 4096 / 0.9 / APC enabled and unchanged context",
        )
    common.require(
        not (client / "storage-cleanup.json").exists(),
        "Remove the active cleanup plan first",
    )
    common.require(
        hashlib.sha256(BUNDLE.read_bytes()).hexdigest() == plan["source_bundle_sha256"],
        "Source bundle differs from the reviewed candidate",
    )
    writes = []
    with zipfile.ZipFile(BUNDLE) as archive:
        for relative in RUNTIME_FILES:
            target = source_root / relative
            common.require(
                not target.is_symlink()
                and target.resolve().is_relative_to(source_root.resolve()),
                "Source must be a regular file inside this experiment",
            )
            allowed = {m["source_sha256"][relative] for m in plan["manifests"].values()}
            common.require(
                hashlib.sha256(target.read_bytes()).hexdigest() in allowed,
                "Refusing to overwrite other source edits: " + relative,
            )
            contents = archive.read(arm + "/" + relative)
            common.require(
                hashlib.sha256(contents).hexdigest()
                == manifest(arm)["source_sha256"][relative],
                "Bundled source hash differs: " + relative,
            )
            compile(contents, str(target), "exec")
            writes.append((target, contents))
    for relative, expected in manifest(arm)["source_sha256"].items():
        if relative not in RUNTIME_FILES:
            common.require(
                hashlib.sha256((source_root / relative).read_bytes()).hexdigest()
                == expected,
                "GPU check changed; review and regenerate plan first",
            )
    for target, contents in writes:
        temporary = target.with_suffix(".gdn-select.tmp")
        with temporary.open("xb") as handle:
            handle.write(contents)
        temporary.replace(target)
    data = (json.dumps(manifest(arm), indent=2) + "\n").encode()
    (ROOT / "variant.json").write_bytes(data)
    (source_root / "csit6000v-variant.json").write_bytes(data)
    (ROOT / "qwen-private-serve/runtime-mode.txt").write_bytes(b"private\n")
    (client / "measurement-mode.txt").write_bytes(b"short\n")
    (client / "service-job-id.txt").write_bytes(b"UNSET\n")
    (client / "server-url.txt").write_bytes(b"http://NODE:8000/v1\n")
    plan["current_local_selection"] = arm
    plan["active_runtime"] = "private"
    PLAN.write_bytes((json.dumps(plan, indent=2) + "\n").encode())
    print("EXPERIMENT=03-gdn-indexed-state ARM=" + arm + " CONFIG=4096/0.9/APC-on CONTEXT=" + str(settings()["max_model_len"]))
    print(
        "Source changed: build first, deploy GPU, wait ready, then submit the independent CPU client."
    )


def compare(baseline, candidate):
    public = common.read_json(PLAN).get("baseline_kind") == "public"
    options = common.read_json(PLAN).get("measurement_options")
    a = common.load_run(baseline, 4096, settings=settings(), service_kind="public", protocol_options=options) if public else common.load_run(
        baseline, 4096, settings=settings(), source_manifest=manifest("baseline"), protocol_options=options)
    b = common.load_run(candidate, 4096, settings=settings(), source_manifest=manifest("candidate"), protocol_options=options)
    result = common.compare_runs(a, b, varying_parameter="public_source_reference" if public else "source")
    result["method"] = (
        "Fuse indexed read and cold-state masking into the Triton chunk state kernel"
    )
    result["borrowed_design"] = "https://github.com/sgl-project/sglang/pull/30169"
    result["concurrency_scope"] = (
        "Serial model pilot only; batched kernel checks do not establish concurrent service gains"
    )
    result["resource_scope"] = (
        "An initial-state intermediate is removed; no measured whole-GPU or energy gain"
    )
    output = (
        ROOT
        / "results"
        / (
            "gdn-comparison-"
            + str(a["report"]["client_job_id"])
            + "-"
            + str(b["report"]["client_job_id"])
            + ".json"
        )
    )
    output.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print("COMPARISON_FILE=" + str(output))
    print(
        json.dumps(
            {
                "quality_gate_passed": result["quality_gate_passed"],
                "first_question_ttft_s": result["latencies"]["first_questions"][
                    "ttft_s"
                ]["mean"],
                "mean_workflow_s": result["mean_six_question_workflow_s"],
            },
            indent=2,
        )
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    choose = commands.add_parser("select")
    choose.add_argument("arm", choices=("public-baseline", "baseline", "candidate"))
    public = commands.add_parser("use-public-baseline")
    public.add_argument("--service-job-id", type=int, required=True)
    public.add_argument("--service-log", type=Path, required=True)
    check = commands.add_parser("compare")
    check.add_argument("baseline", type=Path)
    check.add_argument("candidate", type=Path)
    args = parser.parse_args()
    if args.command == "select":
        select(args.arm)
    elif args.command == "use-public-baseline":
        use_public_baseline(args.service_job_id, args.service_log)
    else:
        compare(args.baseline, args.candidate)


if __name__ == "__main__":
    main()
