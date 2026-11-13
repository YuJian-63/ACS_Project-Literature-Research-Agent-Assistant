# Review output budget

## Approved change

The user selected the 4096-token output-cap option after task `6111bd43-31fb-449b-ab42-f0605a35ae27` failed with `invalid_json` and model finish reason `length`. Its 16000-token total budget left an estimated 5220 tokens after input, but the worker still imposed 2048 output tokens.

## Design

- Only newly submitted real review tasks freeze server-owned `run_config.max_output_tokens=4096`. No public request field, environment setting, dependency, schema migration or prompt-version change is introduced.
- `ResearchJob.max_output_tokens` defaults to 2048. Loading a task without the frozen field retains 2048, including old review-v2 tasks. Summaries and questions retain 2048, and Mock tasks are unchanged.
- Frozen caps must be exact integers (not booleans). Allow 2048 or 4096 for reviews, only 2048 for single-paper tasks; invalid persisted values fail closed with the existing task-input error before a model call.
- For evidence-bearing jobs, the existing preflight rejects an exhausted estimated total budget before model creation. Otherwise request output tokens equal `min(frozen_cap, total_budget - estimated_input_tokens)` with the existing positive lower guard. Post-generation actual-usage checks still enforce the total budget.
- Preserve one model call, no automatic retry/continuation, strict JSON and citation validation, no partial artifact publication, all-empty zero-call completion, frozen versions, timeouts, leases and atomic writes.
- A new task can emit more text and incur greater cost. 4096 is a cap, not reserved use or a guarantee of complete JSON. Existing failed tasks are not edited or rerun.

## Verification and handoff

Use offline submission/loader/worker fixtures to observe the old behavior fail, then prove new versus historical caps, budget boundaries, idempotent replay, real HTTP payload construction via MockTransport, empty evidence and invalid/truncated-result rejection. Run existing backend regressions and syntax/whitespace checks. Restart API and Runner manually, preserving credentials in their original terminals, before submitting a new paid acceptance task. Do not call external models, change data or commit/push in this implementation.

## Subsequent acceptance — 2026-11-13

The user subsequently reported successful task `3cd9c072-c9f5-4b03-9d91-af2abd358570` and confirmed real-run information, review/table content, both papers' citations and physical PDF pages, and refresh recovery. This is one user-observed end-to-end acceptance, not independent verification of that task's actual cap/usage or a guarantee against future truncation. See `../plans/2026-11-13-real-review-acceptance.md`.
