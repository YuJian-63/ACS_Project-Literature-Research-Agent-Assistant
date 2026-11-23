"""Deterministic long-output evidence tasks; all studies are synthetic."""

import hashlib
import json

PROTOCOL = "serial-long-copy-boundary-v2"
COLD_POSITIONS = [0, 3]
WARMUP_POSITIONS = [0, 3]
DOCUMENT_SIZES = {"medium": 72, "long": 216}
SYSTEM = (
    "Use only the supplied synthetic study register. Return exactly one JSON object "
    "with the requested records array and keys, in the requested study order. "
    "Include every requested study. Preserve JSON numbers, booleans and null. "
    "Copy supplied values; do not calculate sums, accuracy, comparisons or conclusions. "
    "An unreported runtime is JSON null. Return compact JSON on one line, without indentation. "
    "Do not add commentary or omit records to shorten the answer."
)


def studies(count):
    datasets = ("Atlas", "Birch", "Cedar", "Delta", "Elm", "Flint", "Grove", "Harbor")
    result = []
    for i in range(count):
        dataset = datasets[i % len(datasets)]
        split = "test" if i % 3 else "validation"
        n_a = 400 + i % 11 * 40
        n_b = n_a if i % 6 else n_a + 80
        runtime_a = 1100 + i % 17 * 37
        result.append({
            "study_id": f"S{i+1:04d}", "evidence_id": f"E{i+1:04d}",
            "dataset_a": dataset, "dataset_b": dataset if i % 4 else datasets[(i + 1) % 8],
            "split_a": split, "split_b": split if i % 5 else ("test" if split == "validation" else "validation"),
            "n_a": n_a, "n_b": n_b, "correct_a": n_a * (65 + i % 13) // 100,
            "correct_b": n_b * (63 + i % 17) // 100,
            "runtime_a_ms": runtime_a, "runtime_b_ms": None if i % 7 == 0 else runtime_a + (i % 9 - 4) * 23,
            "quote": (f"Study S{i+1:04d} evaluates method A on the {dataset} {split} split. "
                      "Its runtime excludes data loading, preprocessing, and network transfer."),
        })
    return result


def render_document(records, family):
    header = (f"SYNTHETIC STUDY REGISTER ({family})\n"
              "Every record reports independent method A and B measurements. "
              "All runtimes are milliseconds. unreported means missing, never zero. "
              "Counts are integers. These are invented benchmark facts, not real research results.\n")
    lines = []
    for r in records:
        runtime_b = "unreported" if r["runtime_b_ms"] is None else str(r["runtime_b_ms"])
        lines.append(
            f"[{r['evidence_id']}] {r['study_id']}: "
            f"A dataset={r['dataset_a']}; split={r['split_a']}; n={r['n_a']}; "
            f"correct={r['correct_a']}; runtime_ms={r['runtime_a_ms']}. "
            f"B dataset={r['dataset_b']}; split={r['split_b']}; n={r['n_b']}; "
            f"correct={r['correct_b']}; runtime_ms={runtime_b}. "
            f"Exact note: \"{r['quote']}\""
        )
    return header + "\n".join(lines) + "\nEND REGISTER\n"


def expected_record(record, task):
    r = record
    if task == "copy":
        return {"study_id": r["study_id"], "dataset": r["dataset_a"],
                "sample_size": r["n_a"], "quote": r["quote"], "evidence_id": r["evidence_id"]}
    if task == "measurements":
        keys = ("study_id", "dataset_a", "split_a", "n_a", "correct_a", "runtime_a_ms",
                "dataset_b", "split_b", "n_b", "correct_b", "runtime_b_ms", "evidence_id")
        return {key: r[key] for key in keys}
    if task == "full_record":
        return dict(r)
    raise ValueError("Unknown extraction task: " + task)


def workload():
    tasks = {
        "copy": (
            "For each requested study, extract method A using exactly these keys: study_id, "
            "dataset, sample_size, quote, evidence_id. quote must copy the entire Exact note "
            "verbatim, including both sentences. Do not paraphrase."
        ),
        "measurements": (
            "For each requested study copy both methods' supplied measurements using exactly "
            "these keys: study_id, dataset_a, split_a, n_a, correct_a, runtime_a_ms, "
            "dataset_b, split_b, n_b, correct_b, runtime_b_ms, evidence_id. "
            "Suffix _a means method A; suffix _b means method B. Copy counts and runtimes "
            "as integers. For unreported B runtime, runtime_b_ms must be null. "
            "Do not compute accuracy, totals, differences, comparisons or new fields."
        ),
        "full_record": (
            "For each requested study copy its complete source record using exactly these "
            "keys: study_id, evidence_id, dataset_a, dataset_b, split_a, split_b, n_a, n_b, "
            "correct_a, correct_b, runtime_a_ms, runtime_b_ms, quote. Suffix _a means method A; "
            "suffix _b means method B. quote is the entire Exact note, verbatim, including "
            "both sentences. Copy numbers as integers; unreported B runtime becomes null. "
            "Do not calculate or infer anything."
        ),
    }
    cases = []
    for family, count in DOCUMENT_SIZES.items():
        records = studies(count)
        indices = [i * (count - 1) // 15 for i in range(16)]
        selected = [records[i] for i in indices]
        document = render_document(records, family)
        ids = ", ".join(r["study_id"] for r in selected)
        for task, question in tasks.items():
            cases.append({
                "id": family + "_" + task, "document_family": family, "task_type": task,
                "study_count": count, "requested_study_count": 16,
                "input_token_target": "approximately 8K" if family == "medium" else "approximately 24K",
                "token_target_scope": "Design target only; actual counts require the course tokenizer",
                "output_goal": "Complete 16-record JSON, naturally ending below max_tokens=4096",
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": document + "\nRequested studies in output order: "
                              + ids + ".\nQuestion: " + question
                              + "\nReturn {\"records\": [...]} containing all 16 requested studies."}],
                "expected": {"records": [expected_record(r, task) for r in selected]},
            })
    return cases


def workload_hash():
    return hashlib.sha256(json.dumps(workload(), sort_keys=True).encode()).hexdigest()


def protocol_options():
    return {"protocol": PROTOCOL, "output_budget": 4096,
            "metrics_sampling": "experiment-boundaries", "workload_sha256": workload_hash(),
            "warmup_requests": 3, "warmup_target_document_requests": 2,
            "warmup_positions": WARMUP_POSITIONS, "warmup_quality_required": False}
