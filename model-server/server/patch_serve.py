"""Configure a temporary course launcher; leave the installed launcher intact."""

import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path


def configure(script, config):
    script, removed_masks = re.subn(
        r"(?m)^[ \t]*(?:export[ \t]+)?CUDA_VISIBLE_DEVICES[ \t]*=[^\n]*(?:\n|$)",
        "",
        script,
    )
    if re.search(r"\bCUDA_VISIBLE_DEVICES[ \t]*=", script):
        raise ValueError("Unrecognized CUDA_VISIBLE_DEVICES assignment in course launcher")
    print("REMOVED_CUDA_VISIBLE_DEVICES_ASSIGNMENTS=" + str(removed_masks), flush=True)
    for key in ("max_model_len", "max_num_seqs", "max_num_batched_tokens"):
        if type(config.get(key)) is not int or config[key] < 1:
            raise ValueError(f"Invalid {key}")
    if not 0 < config.get("gpu_memory_utilization", 0) <= 1:
        raise ValueError("Invalid gpu_memory_utilization")
    for flag, value in (("host", "0.0.0.0"), ("port", "8000")):
        script, count = re.subn(
            r"--" + flag + r"(?:[ \t]+|=)[^\s\\]+(?=\s|\\|$)",
            "--" + flag + " " + value,
            script,
        )
        if count != 1:
            raise ValueError(f"Expected exactly one --{flag} in course serve.sh")
    for key, value in (
        ("max-model-len", config["max_model_len"]),
        ("max-num-seqs", config["max_num_seqs"]),
        ("max-num-batched-tokens", config["max_num_batched_tokens"]),
        ("gpu-memory-utilization", config["gpu_memory_utilization"]),
    ):
        pattern = r"--" + key + r"(?:[ \t]+|=)[0-9.]+(?=\s|\\|$)"
        script, count = re.subn(pattern, "--" + key + " " + str(value), script)
        if count != 1:
            raise ValueError(f"Expected exactly one numeric --{key} in course serve.sh")
    if script.count("--served-model-name") != 1:
        raise ValueError("Course launcher has an unexpected model command")
    if type(config.get("enable_prefix_caching")) is not bool:
        raise ValueError("Set enable_prefix_caching explicitly to true or false")
    # Override the course launcher's setting in its temporary copy only.
    script = re.sub(
        r"(?<!\S)--(?:no-)?enable-prefix-caching(?=\s|$)", "", script
    )
    if re.search(r"--(?:no-)?enable-prefix-caching", script):
        raise ValueError("Unrecognized prefix-caching flag in course launcher")
    prefix_flag = (
        "--enable-prefix-caching"
        if config["enable_prefix_caching"] else "--no-enable-prefix-caching"
    )
    script = script.replace("--served-model-name", prefix_flag + " --served-model-name", 1)
    print("PREFIX_CACHING_REQUESTED=" + str(config["enable_prefix_caching"]).lower(), flush=True)
    if "--disable-access-log-for-endpoints" not in script:
        script = script.replace(
            "--served-model-name",
            "--disable-access-log-for-endpoints /metrics --served-model-name",
            1,
        )
    if "--tool-call-parser" not in script:
        script = script.replace(
            "--served-model-name",
            "--tool-call-parser qwen3_coder --served-model-name",
            1,
        )
    if "--enable-auto-tool-choice" not in script:
        script = script.replace(
            "--served-model-name", "--enable-auto-tool-choice --served-model-name", 1
        )
    if config.get("agent_telemetry") is True:
        if os.environ.get("QWEN_RUNTIME_MODE", "public") != "public":
            raise ValueError("First Agent integration is restricted to the public runtime")
        if "--disable-log-stats" in script:
            raise ValueError("Agent per-request metrics require native statistics logging")
        flags = []
        for name in ("enable-per-request-metrics", "enable-prompt-tokens-details",
                     "enable-force-include-usage", "enable-request-id-headers"):
            if "--no-" + name in script:
                raise ValueError("Conflicting Agent flag in course launcher: " + name)
            if "--" + name not in script:
                flags.append("--" + name)
        if "--middleware" in script or "--default-chat-template-kwargs" in script:
            raise ValueError("Review existing middleware/chat defaults before Agent integration")
        flags.extend(["--middleware agent_telemetry.AgentTelemetryMiddleware",
                      "--default-chat-template-kwargs " + shlex.quote('{"enable_thinking":false}')])
        script = script.replace("--served-model-name", " ".join(flags) + " --served-model-name", 1)
        print("AGENT_TELEMETRY_CONFIG=" + json.dumps({
            "schema": "qwen-agent-telemetry-v1", "stream_passthrough": True,
            "forced_usage": True, "prompt_tokens_details": True, "per_request_metrics": True,
            "periodic_metrics_polling": False, "gpu_scope": "allocated device snapshots",
        }), flush=True)
    if "speculative_config" in config:
        speculative = config["speculative_config"]
        if type(config.get("async_scheduling")) is not bool:
            raise ValueError("Set async_scheduling explicitly for the speculative experiment")
        if speculative is not None:
            if (not isinstance(speculative, dict)
                    or set(speculative) != {"method", "num_speculative_tokens", "prompt_lookup_min", "prompt_lookup_max"}
                    or speculative["method"] != "ngram_gpu"
                    or any(type(speculative[key]) is not int or speculative[key] < 1
                           for key in ("num_speculative_tokens", "prompt_lookup_min", "prompt_lookup_max"))
                    or speculative["prompt_lookup_min"] > speculative["prompt_lookup_max"]
                    or not config["async_scheduling"]):
                raise ValueError("This experiment requires GPU ngram with asynchronous scheduling")
        if "--speculative-config" in script:
            raise ValueError("Course launcher already configures speculation; review it first")
        script = re.sub(r"(?<!\S)--(?:no-)?async-scheduling(?=\s|$)", "", script)
        async_flag = "--async-scheduling" if config["async_scheduling"] else "--no-async-scheduling"
        flags = async_flag
        if speculative is not None:
            flags += " --speculative-config " + shlex.quote(json.dumps(speculative, separators=(",", ":")))
        script = script.replace("--served-model-name", flags + " --served-model-name", 1)
        print("SPECULATIVE_CONFIG_REQUESTED=" + json.dumps(speculative, sort_keys=True), flush=True)
        print("ASYNC_SCHEDULING_REQUESTED=" + str(config["async_scheduling"]).lower(), flush=True)
    return script


if __name__ == "__main__":
    source, output, settings = map(Path, sys.argv[1:])
    config = json.loads(settings.read_text(encoding="utf-8-sig"))
    rendered = configure(source.read_text(encoding="utf-8"), config)
    output.write_bytes(rendered.encode("utf-8"))
    import vllm

    module = Path(vllm.__file__).resolve()
    if "speculative_config" in config:
        support_paths = (
            "config/speculative.py", "config/vllm.py", "v1/spec_decode/ngram_proposer.py",
            "v1/spec_decode/metrics.py", "v1/sample/rejection_sampler.py",
            "v1/worker/gpu_model_runner.py", "v1/spec_decode/ngram_proposer_gpu.py",
        )
        fingerprints = {name: hashlib.sha256((module.parent / name).read_bytes()).hexdigest()
                        for name in support_paths}
        print("SPECULATIVE_RUNTIME_EVIDENCE=" + json.dumps(fingerprints, sort_keys=True), flush=True)
        model_dir = Path(os.environ["QWEN_PROJECT_ROOT"]) / "models/Qwen3.8-27B-AWQ-INT4"
        model_config = json.loads((model_dir / "config.json").read_text())
        index = json.loads((model_dir / "model.safetensors.index.json").read_text())
        mtp_keys = [key for key in index.get("weight_map", {})
                    if re.search(r"(?:^|\.)(?:mtp|nextn|next_n)(?:\.|_|$)", key, re.I)]
        print("MTP_WEIGHT_METADATA=" + json.dumps({
            "architectures": model_config.get("architectures"),
            "num_nextn_predict_layers": model_config.get("num_nextn_predict_layers"),
            "text_config_num_nextn_predict_layers": model_config.get("text_config", {}).get("num_nextn_predict_layers"),
            "matching_index_key_count": len(mtp_keys), "matching_index_keys_sample": mtp_keys[:12],
            "scope": "Metadata only; matching names do not establish MTP execution compatibility",
        }), flush=True)
    scheduler = module.parent / "v1/core/sched/scheduler.py"
    if os.environ.get("QWEN_RUNTIME_MODE") == "public":
        reference = json.loads((settings.parent / "source-reference.json").read_text())
        observed = {}
        for relative in reference["source_sha256"]:
            path = (module.parent / relative.removeprefix("vllm/")).resolve()
            if not relative.startswith("vllm/") or not path.is_relative_to(module.parent.resolve()):
                raise ValueError("Invalid public source reference path")
            observed[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        scheduler_hash = hashlib.sha256(scheduler.read_bytes()).hexdigest()
        evidence = {"source_sha256": observed, "scheduler_sha256": scheduler_hash,
                    "matches_course_archive": observed == reference["source_sha256"]
                    and scheduler_hash == reference["scheduler_sha256"]}
        print("PUBLIC_SOURCE_EVIDENCE=" + json.dumps(evidence), flush=True)
        print("SOURCE_SHA256=" + json.dumps(observed, sort_keys=True), flush=True)
        print("PUBLIC_SERVICE_CONFIG=" + json.dumps(config), flush=True)
        print("VLLM_MODULE=" + str(module), flush=True)
        print("SCHEDULER_SHA256=" + scheduler_hash, flush=True)
        raise SystemExit(0)
    manifest = json.loads((module.parent.parent / "csit6000v-variant.json").read_text())
    scheduler_hash = hashlib.sha256(scheduler.read_bytes()).hexdigest()
    if scheduler_hash != manifest["scheduler_sha256"]:
        raise ValueError("Installed scheduler differs from the selected source variant")
    if "source_sha256" in manifest:
        observed = {}
        source_root = module.parent.parent.resolve()
        for relative, expected in manifest["source_sha256"].items():
            path = (source_root / relative).resolve()
            if not path.is_relative_to(source_root) or not relative.startswith(("vllm/", "benchmarks/")):
                raise ValueError("Invalid source path in manifest")
            observed[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            if observed[relative] != expected:
                raise ValueError("Installed source differs from manifest: " + relative)
        print("SOURCE_SHA256=" + json.dumps(observed, sort_keys=True), flush=True)
    print("PRIVATE_SOURCE_VARIANT=" + json.dumps(manifest), flush=True)
    print("PRIVATE_SERVICE_CONFIG=" + json.dumps(config), flush=True)
    print("VLLM_MODULE=" + str(module), flush=True)
    print("SCHEDULER_SHA256=" + scheduler_hash, flush=True)
