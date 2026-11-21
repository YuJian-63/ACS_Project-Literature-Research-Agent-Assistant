"""Run the selected source's real-GPU check before starting the model server."""

import json
import os
import runpy
import sys
from pathlib import Path

import torch
import vllm

source = Path(vllm.__file__).resolve().parent.parent
manifest = json.loads((source / "csit6000v-variant.json").read_text())
if (
    manifest.get("experiment") == "03-gdn-indexed-state"
    and manifest["variant"] == "gdn-indexed-state"
):
    if torch.cuda.device_count() != 2:
        raise RuntimeError("Kernel check requires the job's two allocated CUDA GPUs")
    check = source / "benchmarks/kernels/benchmark_gdn_indexed_state.py"
    output = (
        source.parent
        / "kernel-checks"
        / ("service-" + os.environ["SLURM_JOB_ID"] + ".json")
    )
    config = (
        Path(os.environ["QWEN_PROJECT_ROOT"])
        / "models/Qwen3.8-27B-AWQ-INT4/config.json"
    )
    if not config.is_file():
        raise RuntimeError("Cannot check actual model dimensions: " + str(config))
    print("GDN_KERNEL_CHECK_BEGIN=real CUDA, 2 GPUs, model head dimensions", flush=True)
    sys.argv = [str(check), "--output", str(output), "--model-config", str(config)]
    runpy.run_path(str(check), run_name="__main__")
else:
    print("GDN_KERNEL_CHECK=not-applicable-to-selected-baseline", flush=True)
