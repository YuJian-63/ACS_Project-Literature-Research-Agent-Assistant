# MVP-2 Multi-Paper Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Enable evidence-grounded real reviews and cross-paper comparison tables for 2–20 selected ready papers.

**Architecture:** Extend the existing server-selected LangGraph Runner without changing its queue or database schema. Retrieve bounded, stable evidence per selected paper, request one structured model response, validate body and table citations against the frozen evidence set, then atomically persist the verified review Artifact.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, LangGraph, Pydantic, React, TypeScript, Vite, existing ignored runtime verification harnesses.

**Spec:** `docs/superpowers/specs/2026-11-12-mvp-2-multi-paper-review.md` and its implementation decisions addendum `docs/superpowers/specs/2026-11-12-mvp-2-review-implementation-decisions.md`.

## Constraints

- Mock review remains unchanged; real summary/qa behavior remains unchanged.
- Only the selected 2–20 ready papers are eligible; SHA-256 snapshot checks remain mandatory.
- Keep total retrieved context bounded and prevent review evidence allocation from favoring earlier papers.
- Use one model call, no tools, no automatic retry, no migration, no vector database, and no network search.
- Every body/table citation must resolve to a verified quote from the row's paper; citation IDs remain server-owned.

## File Map

- `backend/src/app/tasks.py`: allow configured real review without weakening ready-paper checks.
- `backend/src/app/retrieval.py`: stable per-paper review evidence allocation and review prompt schema.
- `backend/src/app/result_validation.py`: validate review comparison table and cross-paper citation ownership.
- `backend/src/app/runner_worker.py`: load multiple frozen papers/chunks and carry selected paper metadata through validation.
- `backend/src/app/lifecycle.py`: persist review title/table atomically while preserving summary/qa output.
- `frontend/src/pages/NewTaskPage.tsx`, `frontend/src/App.tsx`: describe server-selected execution accurately in both the new-task page and global banner.
- `docs/api-contract.md`, `backend/README.md`, `frontend/README.md`: document real review availability and evidence/table behavior.
- `runtime/verify-mvp-2.py`, `runtime/verify-api.py`: temporary unit and DB/API integration checks; runtime files stay ignored.
- `runtime/verify-review-browser.py`: browser-level real Runner review verification using a local fake HTTP model provider.
- `runtime/verify-frontend-real.py`: existing Mock browser regression; its filename does not imply a real model Runner.
- `backend/src/app/research_graph.py`: carry selected paper metadata into the review prompt.

## Tasks

### Task 1: Enable Real Review Submission

**Files:** `backend/src/app/tasks.py`; `runtime/verify-api.py`.

- [x] Add API regression checks: real review without config returns 503 and creates no task; configured review accepts 2 ready papers, rejects 1 paper and any non-ready paper; Mock review remains unchanged.
- [x] Run focused API regression checks; record the mixed TDD/regression execution history honestly below.
- [x] Remove only the real-runner task-type restriction for review; preserve other validation and configuration gates.
- [x] Run real submission and Mock API regression checks.

### Task 2: Balance Review Evidence

**Files:** `backend/src/app/retrieval.py`; `runtime/verify-mvp-2.py`.

- [x] Add checks for deterministic per-paper sampling, at-least-one-per-paper coverage, total chunk/character caps, 2- and 20-paper inputs, all-empty corpora, and impossible coverage under the global budget.
- [x] Implement review selection by reserving the shortest chunk for each paper with evidence, then adding relevant chunks round-robin; fail with `BUDGET_EXCEEDED` if minimum coverage cannot fit.
- [x] Add review prompt instructions/schema for synthesis, missing evidence, incomparable settings, and null table cells.
- [x] Verify summary/qa retrieval and prompt behavior remains unchanged.

### Task 3: Validate Structured Reviews

**Files:** `backend/src/app/result_validation.py`; `runtime/verify-mvp-2.py`.

- [x] Add checks for missing/extra or out-of-order paper rows, duplicate/invalid columns, missing/extra cells, malformed values, uncited non-null research cells, invalid citation indexes, unused citations, and cross-paper table citations.
- [x] Extend validated results with a normalized comparison table and selected-paper ownership constraints.
- [x] Convert model citation indexes to server-owned `C1…Cn` keys after quote and source verification.
- [x] Verify existing summary/qa validation remains byte-compatible and valid review examples pass.

### Task 4: Execute and Persist Review Jobs

**Files:** `backend/src/app/runner_worker.py`, `backend/src/app/lifecycle.py`; `runtime/verify-api.py`.

- [x] Add checks for multi-paper loading, any stale source hash, no-evidence paper rows, all-empty fallback persistence with exact zero counters, atomic review completion, stale-worker rejection, and impossible coverage ending API-visible `failed` with `BUDGET_EXCEEDED`, one failure event, no model calls/artifacts/citations, and no success event.
- [x] Load all selected papers in frozen selection order, validate each status/hash, retrieve balanced evidence, and retain all selected paper IDs/titles.
- [x] Call the existing graph once and validate the returned review against the selected paper set.
- [x] Persist review title, Markdown, comparison table, citations, usage, success status, and event in the existing transaction.
- [x] Run PGlite DB/API integration and Mock worker regressions.

### Task 5: Present Review Results

**Files:** `frontend/src/pages/NewTaskPage.tsx`, `frontend/src/components/ArtifactView.tsx` only if required, frontend/API docs.

- [x] Add UI checks for server-selected execution explanation, review submission copy, table rows, PDF links, and table citation anchors.
- [x] Update execution copy to avoid claiming all tasks use Mock; keep task-specific submission constraints clear.
- [x] Keep the existing comparison table renderer and citation links when their API contract already suffices.
- [x] Run frontend typecheck/build and browser-level review rendering checks.

### Task 6: Integrated Acceptance

- [x] Run all MVP-2 unit, API/database, Mock regression, syntax, and lock checks.
- [x] Run frontend build and browser review flow through Vite, API, Worker, and PGlite.
- [x] Run `git diff --check`; confirm runtime verification scripts remain ignored.
- [x] Record live-provider/native-PostgreSQL limitations without claiming unrun acceptance.

## Commit Boundary

- Commit the verified MVP-2 feature only when explicitly requested; do not push unless requested.

## Execution Record - 2026-11-12

All six implementation/acceptance tasks are complete. The checklist describes delivered checks and behavior, not a claim that every check was observed RED before implementation. Some checks were added as regressions of already-working behavior; the malformed NUL column-label check exposed a failure and passed after validation was tightened.

### Fresh Acceptance Evidence

- `backend/.venv/Scripts/python.exe runtime/verify-mvp-2.py`: 15 tests passed, including deterministic 2/20-paper coverage, budget bounds, table ownership/shape/text validation, all-empty fallback, and every-paper source-hash recheck.
- `backend/.venv/Scripts/python.exe runtime/verify-mvp-1b.py`: 14 tests passed for existing retrieval, prompts, result validation, model adapter, configuration, and deadline behavior.
- `node runtime/verify-api.cjs`: 24 API/database tests passed; the separate Uvicorn/Mock Worker restart, recovery, persistence, and terminal replay checks also passed. The API checks include submission gates/idempotency, partial/all-empty evidence, budget failure, atomic rollback, lease loss, and same-paper citations.
- `node runtime/verify-parsing.cjs`: parser integration passed, including extraction, atomic evidence persistence, failure cases, recovery, stale writes, rollback, timeout, shutdown, and Mock compatibility.
- `npm.cmd --prefix frontend run build`: TypeScript checks and production build passed.
- `backend/.venv/Scripts/python.exe -m compileall -q backend/src`: passed.
- `uv lock --check --offline --directory backend`: passed (58 packages); no dependency or migration changes.
- `git diff --check`: passed; `git ls-files runtime` is empty and verification scripts/screenshots remain ignored.

### Browser Acceptance

With `PLAYWRIGHT_BROWSERS_PATH=runtime/pw-browsers`, run `node runtime/verify-frontend-real.cjs`:

- Set `BROWSER_CHECK_SCRIPT=runtime/verify-review-browser.py` for the real Runner path. Passed: two PDF uploads, real parser and Runner, local fake OpenAI-compatible HTTP model, persisted comparison table, same-paper citations/PDF links, anchor navigation, reload, mobile layout, rerun, and Token-budget failure. Screenshots remain in ignored `runtime/frontend-shots/review-desktop.png` and `review-mobile.png`.
- Unset `BROWSER_CHECK_SCRIPT` for the existing Mock browser flow. Passed: upload, summary, reload/persistence, events, artifact, original file, rerun, budget failure, and task list. This is not evidence of live model execution.

### Limits and Delivery Boundary

- Model-output token cap remains 2048 (or the smaller remaining budget); large 20-paper/multi-column responses may fail structured validation. No silent truncation acceptance, retries, or multi-call orchestration is introduced.
- These database checks use isolated PGlite instances, not a production database or native PostgreSQL concurrency acceptance.
- No live model provider credentials were used; local fake-provider checks verify the real execution path, not model synthesis quality.
- The implementation remains uncommitted and unpushed pending an explicit user request. Temporary verification assets intentionally remain local and ignored, following the existing repository convention.

### Final Review and Visual Follow-Up

- An independent read-only code review found no actionable correctness defects in the review retrieval, validation, persistence/fencing, and compatibility changes; its fresh 15+14 unit rerun also passed.
- Visual inspection then caught stale global shell copy still claiming no Agent was connected, despite real Runner execution. This originates in `frontend/src/App.tsx`, not the new-task page.
- Added browser assertions for the neutral server-configured execution banner and MVP-2 label; observed RED with actual text describing simulation, then replaced the obsolete global text without adding client-side runner detection or changing task-specific Mock notices.
- GREEN after the shell-copy fix: reran the complete real Runner/fake-provider browser flow with the new assertions, the unchanged Mock browser flow, and frontend typecheck/build; all passed. Reinspected the mobile screenshot to confirm the banner and comparison table render correctly.
