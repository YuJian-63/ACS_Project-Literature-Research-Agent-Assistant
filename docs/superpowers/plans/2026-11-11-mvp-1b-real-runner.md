# MVP-1B Real Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver evidence-grounded real paper summaries and QA while preserving the existing Mock Runner.

**Architecture:** Keep server-selected Mock/real execution and share the existing lease/heartbeat/recovery boundaries. Add a LangGraph task flow with bounded evidence retrieval, a replaceable OpenAI-compatible model adapter, strict citation validation, and atomic artifact/citation completion. The frontend consumes existing artifact APIs and displays verified citations.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, PostgreSQL, LangGraph, OpenAI-compatible HTTP, React, TypeScript, Vite.

**Spec:** `docs/superpowers/specs/2026-11-11-mvp-1b-real-runner.md`

## Global Constraints

- Mock remains the default and keeps its current output, empty citations, and null usage.
- Real tasks support only `summary` and `qa`; review/search/cross-paper synthesis remain unavailable.
- Real tasks require ready papers and bind to the paper IDs and SHA-256 snapshots captured at submission.
- Missing real model configuration returns `503 RUNNER_NOT_CONFIGURED` before persisting a task.
- Model prompts, paper text, raw responses, and API keys must not appear in logs or task events.
- Do not add a database migration or public arbitrary-chunk endpoint.
- Validate every citation against selected paper, chunk ID, physical page, and exact stored quote before completion.
- Preserve task time/step/token budgets, lease ownership, and atomic artifact/citation/status/event writes.

## Review Focus

- **Wrong-source citations:** reject valid-looking quotes from unselected papers or chunks; pin to result-validation tests.
- **Prompt-injected paper text:** treat PDF content as data and never enable tools; pin to prompt/client tests.
- **Lost lease during model call:** prevent all artifact, citation, and usage writes by the stale owner; pin to worker lifecycle tests.
- **Unavailable or malformed model response:** fail safely without exposing secrets or partial artifacts; pin to adapter/worker tests.
- **Mock compatibility:** keep existing Mock API responses, copy, and usage unchanged; pin to regression checks.

## File Map

- `backend/src/app/config.py`, `.env.example`: server-side runner/model configuration and validation.
- `backend/src/app/tasks.py`, `api.py`, `schemas.py`: runner snapshot, task preconditions, error and artifact response contracts.
- `backend/src/app/model_client.py`, `research_graph.py`: replaceable model protocol/HTTP adapter and bounded LangGraph workflow.
- `backend/src/app/retrieval.py`, `result_validation.py`: selected-paper evidence packing and strict structured-result/citation checks.
- `backend/src/app/lifecycle.py`, `runner_worker.py`: runner-aware claiming, lease/heartbeat, budget checks, and atomic real completion.
- `frontend/src/api/types.ts`, `components/ArtifactView.tsx`: paper title and verified citation presentation.
- `docs/api-contract.md`, `backend/README.md`, `frontend/README.md`: runtime/API behavior and setup instructions.
- `runtime/verify-mvp-1b.py`: temporary verification harness only; never commit runtime artifacts.

## Tasks

### Task 1: Server Runner Selection

**Files:** `backend/src/app/config.py`, `.env.example`, `backend/src/app/tasks.py`, `backend/src/app/errors.py`; temporary `runtime/verify-mvp-1b.py`.

- [ ] Add failing checks for default Mock snapshot, configured real snapshot, ready-only paper validation, unsupported real `review`, and missing-model `503 RUNNER_NOT_CONFIGURED` with no task row.
- [ ] Run the checks and confirm each fails for the expected missing behavior.
- [ ] Add validated `TASK_RUNNER`, model endpoint/model/API-key/timeouts/context-budget settings; default to Mock.
- [ ] Snapshot runner/model/workflow/prompt settings on task creation; keep idempotency behavior stable and reject only real-mode unsupported inputs.
- [ ] Re-run checks and the existing Mock API verification script.

### Task 2: Bounded Evidence and Model Workflow

**Files:** `backend/src/app/retrieval.py`, `model_client.py`, `research_graph.py`, `backend/pyproject.toml`, `backend/uv.lock`; temporary runtime checks.

- [ ] Add failing checks for selected-paper-only retrieval, deterministic QA ranking, per-paper summary coverage, context caps, and no-evidence behavior.
- [ ] Add failing adapter checks for auth header, structured output parsing, timeout, non-2xx response, malformed JSON, and no prompt/response/key logging.
- [ ] Implement bounded chunk selection preserving paper/chunk/page identity; reject stale file hashes and never include unselected paper text.
- [ ] Implement a model-client protocol and OpenAI-compatible Chat Completions adapter with injectable fake client.
- [ ] Implement a small LangGraph flow that only creates the structured draft; do not enable tools or implicit retries beyond frozen budgets.
- [ ] Lock dependencies and run parser/Mock regression plus adapter/workflow checks.

### Task 3: Citation Validation and Real Worker

**Files:** `backend/src/app/result_validation.py`, `lifecycle.py`, `runner_worker.py`, `backend/src/app/db/models.py` only if an existing field is insufficient; temporary DB/process checks.

- [ ] Add failing checks for wrong paper/chunk/page, quote not an exact substring, duplicate/unused citation marker, malformed structure, and empty unsupported conclusion.
- [ ] Add failing lifecycle checks for stale owner rejection, timeout/budget failure, model exception handling, and atomic rollback of artifact/citations/usage/status/event.
- [ ] Validate structured model output, assign server-owned `C1…Cn`, and render consistent Markdown markers.
- [ ] Add runner-aware claim/heartbeat/execute paths while preserving Mock claim semantics and recovery behavior.
- [ ] Atomically persist the real artifact, citations, known usage, succeeded event, and terminal state after rechecking lease ownership.
- [ ] Run full temporary database/process fault-injection checks and existing Mock worker regression.

### Task 4: Artifact API and Citation UI

**Files:** `backend/src/app/api.py`, `schemas.py`, `frontend/src/api/types.ts`, `frontend/src/components/ArtifactView.tsx`, `docs/api-contract.md`.

- [ ] Add failing API checks for real artifact retrieval, citation paper title, Mock empty citations, nonterminal empty result, and citation page consistency.
- [ ] Update the artifact query to return validated real citations with paper title while preserving the current response shape otherwise.
- [ ] Update frontend citation links to show paper title and physical page, linking to the original PDF page and quote anchor.
- [ ] Run API/Mock regressions and frontend typecheck/build.

### Task 5: Integrated Documentation and Acceptance

**Files:** `backend/README.md`, `frontend/README.md`, `docs/api-contract.md`, temporary `runtime/verify-mvp-1b.py`.

- [ ] Verify startup instructions for Mock and configured real Runner modes, including required environment variables and unsupported task types.
- [ ] Run backend syntax/import checks, dependency lock validation, complete Mock regressions, and the MVP-1B fake-model/database fault-injection harness.
- [ ] Run frontend production build and browser verification for real citations plus unchanged Mock messaging.
- [ ] Run `git diff --check`; inspect staged/unstaged changes and confirm runtime files are ignored.
- [ ] Record unavailable real provider/PostgreSQL limitations without claiming live service acceptance.

## Commit Boundaries

- Commit each independently verified task only when explicitly requested; do not push unless requested.

## Execution Record — 2026-11-11

- Implemented the real summary/QA path, evidence retrieval, model adapter, citation validation, runner-specific task lifecycle, artifact API, frontend citations, and setup/API documentation.
- Bound each provider request by both the configured model timeout and the task's remaining execution budget; the deadline helper has regression coverage for active and expired tasks.
- Verified: 14 fake-model/unit checks, 16 API/database integration checks, independent Uvicorn/Worker persistence and recovery checks, browser flow through Vite/API/Worker/PGlite, backend compile check, locked dependency check, frontend production build, and `git diff --check`.
- Runtime verification scripts remain ignored and are not part of the Git change set.
- Not verified against a live model provider or native PostgreSQL; browser verification used the repository's bundled Chromium and PGlite.
- Changes remain uncommitted and unpushed.
