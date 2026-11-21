"""Verify the unchanged shared public runtime without editing its installation."""

import importlib.metadata
import json
import os
import sys
from pathlib import Path

import torch
import transformers
import vllm
import vllm._C_stable_libtorch

public = Path(os.environ["QWEN_PROJECT_ROOT"]) / "vllm-env"
assert Path(sys.prefix).resolve() == public.resolve(), sys.prefix
for module in (vllm, vllm._C_stable_libtorch, torch, transformers):
    path = Path(module.__file__).resolve()
    assert path.is_relative_to(public.resolve()), path
    print(module.__name__ + " " + str(path), flush=True)
print("PUBLIC VLLM / PUBLIC DEPENDENCIES CHECK PASSED", flush=True)
print("RUNTIME_VERSIONS=" + json.dumps({
    "vllm": vllm.__version__, "torch": str(torch.__version__),
    "transformers": transformers.__version__, "triton": importlib.metadata.version("triton"),
}), flush=True)
