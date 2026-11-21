"""Print read-only startup evidence without importing CUDA or starting clients."""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


COURSE = Path("/mnt/home/public/course-envs/CSIT6000V")
MODEL = "models/Qwen3.8-27B-AWQ-INT4"
PHASES = ("before-activation", "after-activation", "after-kernel-check")


def emit(label, value):
    print(label + "=" + json.dumps(value, sort_keys=True), flush=True)


def fingerprint(path):
    result = {"path": str(path)}
    try:
        result.update(resolved=str(path.resolve()), exists=path.is_file())
        if path.is_file():
            size = path.stat().st_size
            result["bytes"] = size
            if size <= 2 * 1024 * 1024:
                result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                result["hash_scope"] = "metadata only; file exceeds 2 MiB"
    except OSError as exc:
        result["error"] = str(exc)
    return result


def command(label, args):
    print("STARTUP_PROBE_" + label + "_BEGIN", flush=True)
    try:
        result = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=10, universal_newlines=True, check=False,
        )
        output = result.stdout or ""
        snippet = output[:16000]
        print(snippet, end="" if snippet.endswith("\n") else "\n", flush=True)
        emit("STARTUP_PROBE_" + label + "_RESULT", {
            "returncode": result.returncode, "output_truncated": len(output) > 16000,
        })
    except (OSError, subprocess.TimeoutExpired) as exc:
        emit("STARTUP_PROBE_" + label + "_UNAVAILABLE", str(exc))
    print("STARTUP_PROBE_" + label + "_END", flush=True)


def runtime_files():
    projects = {
        "public": COURSE / "project/qwen3.8-27b-v1",
        "private_course": COURSE / "project-private-vllm/qwen3.8-27b-v1",
    }
    files = []
    for name in ("project", "project-private-vllm"):
        files.append(fingerprint(COURSE / name / "activate.sh"))
    memory_paths = (
        "vllm/v1/worker/gpu_worker.py", "vllm/v1/worker/utils.py",
        "vllm/utils/mem_utils.py", "vllm/v1/executor/multiproc_executor.py",
    )
    for project in projects.values():
        files.append(fingerprint(project / "serve.sh"))
        for name in ("config.json", "generation_config.json", "tokenizer_config.json",
                     "model.safetensors.index.json"):
            files.append(fingerprint(project / MODEL / name))
        for relative in memory_paths:
            files.append(fingerprint(project / "vllm-env/lib/python3.12/site-packages" / relative))
    private_env = os.environ.get("QWEN_PRIVATE_ENV")
    if private_env:
        for relative in memory_paths:
            files.append(fingerprint(Path(private_env).parent / "vllm-src" / relative))
    emit("STARTUP_RUNTIME_FILE_FINGERPRINTS", files)

    public = projects["public"] / MODEL
    private = projects["private_course"] / MODEL
    comparison = {"public_directory": str(public), "private_directory": str(private)}
    try:
        public_files = {p.name: p for p in public.glob("*.safetensors")}
        private_files = {p.name: p for p in private.glob("*.safetensors")}
        comparison["shard_names_match"] = bool(public_files) and public_files.keys() == private_files.keys()
        shards = []
        for name in sorted(public_files.keys() | private_files.keys()):
            a, b = public_files.get(name), private_files.get(name)
            record = {"name": name, "present_public": a is not None, "present_private": b is not None}
            if a is not None and b is not None:
                try:
                    record.update(public_bytes=a.stat().st_size, private_bytes=b.stat().st_size,
                                  public_resolved=str(a.resolve()), private_resolved=str(b.resolve()),
                                  same_file_object=os.path.samefile(str(a), str(b)))
                except OSError as exc:
                    record["error"] = str(exc)
            shards.append(record)
        comparison["shards"] = shards
        comparison["all_shards_same_file_object"] = bool(shards) and all(
            shard.get("same_file_object") is True for shard in shards)
        comparison["scope"] = (
            "No weight data is read. A shared file object establishes identity; "
            "different file objects or equal sizes alone do not establish byte equality."
        )
    except OSError as exc:
        comparison["error"] = str(exc)
    emit("STARTUP_PUBLIC_PRIVATE_WEIGHT_METADATA", comparison)


def main():
    phase = sys.argv[1] if len(sys.argv) == 2 else "unknown"
    if phase not in PHASES:
        raise ValueError("Unknown startup diagnostic phase: " + phase)
    names = (
        "SLURM_JOB_ID", "SLURM_JOB_NODELIST", "SLURM_JOB_GPUS", "SLURM_STEP_GPUS",
        "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER",
        "QWEN_RUNTIME_MODE", "QWEN_PROJECT_ROOT", "QWEN_PRIVATE_ENV",
        "PYTORCH_CUDA_ALLOC_CONF", "PYTORCH_ALLOC_CONF", "CUDA_MODULE_LOADING",
    )
    emit("STARTUP_DIAGNOSTICS_BEGIN", {
        "phase": phase, "host": socket.gethostname(), "pid": os.getpid(),
        "uid": os.getuid(), "environment": {name: os.environ.get(name) for name in names},
    })
    # Use a distinct CSV layout so existing service-evidence parsers still read
    # the original authoritative post-selection two-GPU inventory.
    command("GPU_MEMORY", [
        "nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free",
        "--format=csv",
    ])
    command("GPU_PROCESSES", [
        "nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
        "--format=csv",
    ])
    command("OWN_PROCESSES", [
        "ps", "-u", str(os.getuid()), "-o", "pid=,ppid=,pgid=,user=,comm=",
    ])
    if phase == "after-activation":
        runtime_files()
    emit("STARTUP_DIAGNOSTICS_END", {"phase": phase})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Diagnostics are advisory; ordinary environment, source and GPU
        # checks retain responsibility for accepting or rejecting startup.
        emit("STARTUP_DIAGNOSTICS_UNAVAILABLE", {"error": str(exc)})
