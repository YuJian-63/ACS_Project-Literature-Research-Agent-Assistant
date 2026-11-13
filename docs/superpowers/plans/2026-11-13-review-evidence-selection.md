# Review Evidence Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give real multi-paper review server-owned exact quotations and citation numbering through a versioned evidence-selection protocol.

**Architecture:** Resolve task-wide evidence IDs into one first-use citation pool for paragraphs and table cells. Adapt that draft into the existing strict review validator and keep the atomic persistence path unchanged.

**Tech Stack:** Existing Python, Pydantic, SQLAlchemy and LangGraph; unittest fixture checks.

**Spec:** `docs/superpowers/specs/2026-11-13-review-evidence-selection.md`

## Global Constraints

- New review tasks freeze `evidence-review-v2`; old and missing-version review jobs retain v1.
- Keep single-paper v4, database schema, frontend, budgets and one-call execution unchanged.
- No paid model requests, automatic task submissions, output repair, automatic retry or Git commits.
- Keep existing ignored runtime checks; formal tracked test/CI adoption remains separate work.

## Review Focus

- Reused and table-only evidence must share consistent citation numbers.
- Empty/partial evidence must preserve honest nulls and the zero-call all-empty path.
- Wrong-paper selections and forged identity/quote/index overrides must fail closed.
- Table key insertion order must not change numbering; declared columns control traversal.
- Frozen and missing-version jobs must never silently use the new parser.

### Task 1: Protocol and resolver

**Files:** `backend/src/app/result_validation.py`, `backend/src/app/retrieval.py`, `runtime/verify-review-evidence-selection.py`.

- [x] Add failing checks for exact passage input, paragraph/table ID resolution, shared and table-only citations, column-order numbering, partial evidence/nulls, schema limits, ownership and tampering rejection, legacy compatibility.
- [x] Run the new checks and confirm failures are due to missing v2 behavior.
- [x] Add strict v2 draft models and `validate_selected_review_result(raw, evidence, selected_papers)`; adapt resolved content to `validate_review_result` for unchanged final validation.
- [x] Add v2 prompt while retaining explicit v1 behavior. Reuse `build_citation_passages`; include source paper IDs in review input.
- [x] Run focused resolver/prompt checks.

### Task 2: Frozen version and Runner

**Files:** `backend/src/app/tasks.py`, `backend/src/app/runner_worker.py`, `runtime/verify-review-evidence-selection.py`, historical runtime checks if their default-version assumptions need pinning.

- [x] Add failing checks for new-task version freezing, loading v1/v2/missing versions, actual-prompt token estimation, worker dispatch, one-call success/failure, all-empty no-call completion and failed-result nonpublication.
- [x] Freeze v2 on new real review tasks; keep the workflow version and historical loader fallback unchanged.
- [x] Dispatch v2 to the new resolver without changing ownership, stage, usage or artifact persistence.
- [x] Run new checks and the existing seven regression suites, preserving explicit historical assertions.

### Task 3: Documentation and handoff

**Files:** `backend/README.md`, `docs/api-contract.md`, this plan and spec.

- [x] Document internal v2 schema, version boundaries and unchanged public artifacts.
- [x] Review the final patch for bounds, source isolation, frozen versions and unchanged transactions; run syntax and whitespace checks.
- [x] Record actual verification counts and limitations, then guide API/Runner restart and one new two-paper manual acceptance. Do not claim live acceptance before the user executes it.

## Execution ledger

- Ruling: continue in the user's existing working tree without a new branch or worktree, preserving preexisting uncommitted integration changes. This is an incremental continuation, not a clean isolated feature branch; no Git write was authorized.
- The initial 32-test run exposed missing v2 resolver/prompt/dispatch behavior. Three submission fixtures also lacked a required dummy database URL; corrected only that fixture, then separately observed the version-freeze assertion fail on v1 before restoring the v2 change. No real database or provider was used.
- All 32 new review checks passed, followed by all 128 checks across the eight combined suites. Rejection-path warning logs are expected fixture outcomes, not real task failures. Legacy tests required no changes.
- Syntax checks passed for 30 backend Python files and the new runtime check. `git diff --check` passed; only standard LF/CRLF notices appeared. Secrets and runtime checks remain ignored.
- A read-only local API paper-list request could not complete; no task was submitted and no service was restarted. Live paper selection and review acceptance remain pending.
- A synthetic two-paper input with 24 stored chunks produced 48 task-unique passages and an estimated 11328 input tokens, leaving the unchanged 2048 output cap within a 16000 task budget. This is only a local fixture estimate, not a measurement for the user's papers or provider usage.
- Independent scoped review reported no blocking findings and reran the 32 review checks plus eight additional ad hoc bounds/extra-field checks. The reproducible combined suite count remains 128; ad hoc reviewer checks are not counted as tracked regression tests. No code change was requested by review.
- Handoff: restart only API and real Runner in their original backend terminals, preserving database/storage settings. Obtain two distinct ready papers and check budget before a new paid review submission. Real generation, semantic support, PDF navigation and refresh recovery are still pending manual acceptance. No commit or push was made.

## Subsequent manual acceptance — 2026-11-13

Following the separate review-output-budget adjustment, the user reported successful task `3cd9c072-c9f5-4b03-9d91-af2abd358570` and confirmed real execution information, review/table coverage, both papers' citations and physical PDF pages, and refresh recovery. This closes the earlier pending live gate for one user-observed two-paper review, not general generation reliability. No independent task/configuration/usage inspection or further model call was performed by the agent during closeout. See `docs/superpowers/plans/2026-11-13-real-review-acceptance.md`.
