# MVP-2 Review Edge-Case Decisions

This addendum makes the edge-case behavior in `2026-11-12-mvp-2-multi-paper-review.md` executable and testable, and overrides the parent spec wherever it explicitly defines a narrower edge-case exception.

## All-Empty Corpus

- If every selected ready paper has zero stored chunks, skip the model client entirely and complete the task successfully.
- Return Markdown that explicitly says the selected papers contain no parsed evidence available for synthesis.
- Return a single comparison column: `evidence_status` / `证据状态`.
- Return one row per selected paper in selection order. Every row's `evidence_status` cell value is `未检索到可用解析证据` with an empty `citation_keys` list.
- Persist zero citations and exact usage counters: `input_tokens=0`, `output_tokens=0`, `model_calls=0`, and `tool_calls=0` (therefore `total_tokens=0`).

## Minimum Coverage Cannot Fit

- Before model invocation, reserve one shortest chunk for every selected paper that has at least one chunk.
- If the reserved set would exceed `evidence_context_chars` or the global chunk cap, fail the task with `BUDGET_EXCEEDED`.
- Do not invoke the model or create an Artifact/Citation; the task has a failure event and no success event.
- Papers with no chunks do not cause this failure; they remain represented as null/unreported rows in a model-generated comparison table if other papers have evidence.

## Table Citation Invariants

- Require every non-null research-content comparison cell to reference at least one citation candidate. The reserved `evidence_status` fallback cell is metadata about retrieval, not a research claim, and has no citation.
- Each candidate citation must point to an evidence chunk from the same paper as the table row.
- Persist only server-generated `C1…Cn` keys after validating exact quote substrings and all paper/chunk/page identities.

## Compatibility

- Mock `review` retains its current simulated artifact and null comparison table.
- Real `summary` and `qa` retain their current prompt, result shape, and null comparison table.
