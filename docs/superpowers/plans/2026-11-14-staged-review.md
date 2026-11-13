# Staged Literature Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reliable multi-paper reviews with server budgets and no user tuning.
**Architecture:** Frozen automatic policy; per-paper evidence analysis; short synthesis units; durable fenced checkpoints; deterministic validated artifacts.
**Tech Stack:** Python, Pydantic, SQLAlchemy/PostgreSQL, Alembic, React/TypeScript.
**Spec:** ../specs/2026-11-14-staged-review-design.md

## Global Constraints

- Existing tasks keep their workflow versions; no paid requests, commits or live database changes.
- Hard limits: 100 calls, 100000 cumulative tokens, 1800 seconds; at most two attempts per unit.
- Preserve strict evidence/source ownership and public artifact structure.

## Review Focus

- Uncertain network outcomes retain reservations across worker replacement.
- A model response containing valid JSON but invalid evidence must never become a checkpoint.
- Same-key replay must precede policy/model/config checks, including legacy hashes.
- Long questions and twenty papers must fit all individual and cumulative context budgets.
- UI switching and refresh must preserve submission identity and existing results.

### Task 1: Automatic policy and protocol

Files: research/review_policy.py, research/review_protocol.py, tracked backend tests.
- [x] Add failing budget and protocol tests; observe failures.
- [x] Implement deterministic planning, per-paper source sampling and validated small-unit prompts.
- [x] Verify 2/6/20 scale, limits, evidence ownership and final assembly.

### Task 2: Durable execution and task submission

Files: db/models.py, Alembic revision, research/review_store.py, research/review_runner.py, tasks/service.py, tasks/lifecycle.py, workers/research.py, config.py, API schemas/views.
- [x] Add failure tests for accounting, resume, fencing and legacy request hashes.
- [x] Implement immutable auto policy, persisted attempt reservations, progress and bounded local retries.
- [x] Route new reviews to the staged runner; preserve historical dispatch and deadline behavior.
- [x] Verify isolated PostgreSQL migration and task transactions.

### Task 3: Review user experience

Files: frontend task submission/types/page, progress formatting and catalogs.
- [x] Cover review payloads without budgets and translated progress.
- [x] Remove review budget controls; add read-only auto allocation and estimated usage labels.
- [x] Verify frontend build and locale regressions.

### Task 4: Documentation and regression

Files: API contract, database design, README and this plan.
- [x] Document migration, automatic budgeting, retries, limits and live acceptance.
- [x] Run focused and existing offline regressions; inspect diff and report limitations.

## Execution ledger

- Initial: user approved approach 2. Working tree clean at start. Implement in existing workspace because the user collaborates here; no branch or commit requested.

- 2026-11-14: implemented policy/protocol, durable reservations and atomic successful checkpoints, versioned task dispatch and review UX; migration 20261114_0003 and reference DDL updated.
- Independent read-only review found byte-estimation undercount, serialized Unicode growth, settlement/checkpoint crash window and missing synthesis source passages. Reproduced with failing regressions, then addressed all four. Synthesis uses relevant validated columns plus deduplicated original passages; serialized bytes are bounded and planned. Input reservations use UTF-8 bytes plus message overhead for the supported byte-tokenized compatible provider, not exact billing estimates.
- Capacity adjustment: preserve at least 1000 source characters per paper where available. Two/six-paper full fixtures and twenty-paper sparse fixtures pass; twenty full fixtures exceed the hard cumulative ceiling and are rejected before requests rather than reducing source evidence further. Large/long-question submissions can legitimately return REVIEW_CAPACITY_EXCEEDED. No universal twenty-paper capacity claim.
- Backend: 34 tracked tests passed with isolated PostgreSQL17 at 127.0.0.1:55433/review_tests. Includes upgrade/downgrade/re-upgrade + alembic check, four concurrent claimers, original-deadline timeout while requeued, six-paper nine-call execution, replay compatibility, invalid JSON/length retries, usage without full reporting, atomic second-attempt success, checkpoint recovery and stale owner rejection. Empty or irrelevant sections use explicit insufficient-evidence text without unsupported model claims.
- Frontend: typecheck/build, verify:review and isolated Chromium six-paper fixture passed (POST omits budget, automatic allocation, estimated usage, Chinese/English progress, refresh and390px). Existing i18n/core/artifact title browser regressions passed earlier in this execution.
- Legacy offline backend regressions passed: MVP2(15), model thinking(8), evidence selection(24), paragraph citations(20), result diagnostics(7), citation prompt(8), parser deadline, review evidence(32), review output budgets(18). Ignored runtime fixtures were adapted to explicitly distinguish legacy persisted tasks from new staged submissions.
- Development completion (before the user acceptance below): live acceptance was pending; no paid model calls or business database migrations performed. User must upgrade their selected database and restart API/Runner before creating a new six-paper review. Existing task IDs retain historical behavior. No commit/push requested or performed.

- Final independent confirmation: section-scoped prompt/validation and partial-evidence skip behavior resolved; 25 offline policy/store/runner checks passed in reviewer run. Main final suite: 34 tests passed including native PostgreSQL. Dedicated tmpfs test container acs-staged-review-tests-20261114 was identified by its staged-review-tests label and stopped/removed; business container left untouched. git diff --check passed.

## Live six-paper acceptance — 2026-11-14

Task: eb3b4c9e-39db-4e19-bd88-5e64faeb9941.

The user supplied migration output showing upgrade from 20261112_0002 to 20261114_0003, current head 20261114_0003 and alembic check with no new upgrade operations. After the restart instructions, the user confirmed model configuration and API health/readiness checks were normal. They then created a new six-paper review and reported successful execution.

The user subsequently confirmed all four requested acceptance checks were normal:

- Complete review prose without visible truncation or residual JSON; insufficient evidence clearly identified where applicable.
- Six paper rows with research objective, method, evaluation and limitations columns; missing evidence may remain empty.
- A sampled prose citation and table citation trace to the corresponding paper, source passage and PDF page, with table citations belonging to the row paper.
- Refresh preserves the completed result, comparison table, citations, runtime statistics and automatic allocation display.

This closes the requested live six-paper functional acceptance based on user feedback. The agent did not independently fetch or rerun this task, inspect its frozen policy, count actual requests/retries or verify reported Token usage. This one success does not establish reliability for every paper count or prove live worker-crash recovery, maximum-output handling or network-failure retries; those boundaries retain their offline/native-test evidence. No Git commit or push was performed.
