"""Fast screening subset of the long-input workload."""
import hashlib
import json
from long_workload import workload as full_workload

PROTOCOL = "serial-long-copy-screen-v1"
CASE_IDS = ("medium_measurements", "medium_full_record", "long_measurements", "long_full_record")
WARMUP_POSITIONS = [0, 2]
COLD_POSITIONS = [0, 2]

def workload():
    all_cases = {case["id"]: case for case in full_workload()}
    return [all_cases[name] for name in CASE_IDS]

def workload_hash():
    return hashlib.sha256(json.dumps(workload(), sort_keys=True).encode()).hexdigest()

def protocol_options():
    return {"protocol": PROTOCOL, "output_budget": 4096,
            "metrics_sampling": "experiment-boundaries", "workload_sha256": workload_hash(),
            "warmup_requests": 3, "warmup_target_document_requests": 2,
            "warmup_positions": WARMUP_POSITIONS, "trials": 2,
            "cases_per_trial": 4}
