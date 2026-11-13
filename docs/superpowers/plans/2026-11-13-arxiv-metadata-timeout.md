# arXiv Metadata Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow slow metadata responses without relaxing the total request deadline or PDF protections.

**Architecture:** Set only the HTTPX metadata read phase to at most 15 seconds; reuse the existing supervised transport and deadlines unchanged.

**Tech Stack:** Existing Python, HTTPX and unittest fixtures.

**Spec:** `docs/superpowers/specs/2026-11-13-arxiv-metadata-timeout.md`

## Global Constraints

- Metadata read <=15 seconds; other phases and all PDF phases <=5 seconds; every phase is clamped to the remaining request budget.
- Preserve the 20-second metadata total deadline, watchdog, source gate, no retry and all source protections.
- Preserve the existing working tree and ignored runtime-test convention. No model calls, task creation or Git writes.

## Review Focus

- A shorter remaining budget must not become a fresh 15-second wait.
- Exact-version metadata and search must behave identically.
- Slow/failed requests must not introduce retries or bypass source permits.
- PDF and transport security options must remain unchanged.

### Task 1: Regression and minimal fix

**Files:** `runtime/verify-arxiv-timeouts.py`, `backend/src/app/arxiv_transport.py`.

- [x] Add and run failing tests for slow metadata and per-phase budgets; confirm failure on the existing 5-second read cap.
- [x] Override only metadata read timeout, retaining default phase limits.
- [x] Run focused tests, the existing arXiv suite and prior research regression suites, including real local child watchdog checks where available.

### Task 2: Documentation and handoff

**Files:** `backend/README.md`, `docs/api-contract.md`, this plan and spec.

- [x] Update operational timeout descriptions; review the patch and run syntax/whitespace checks.
- [x] Record exact results and provide restart/fallback guidance. Preserve the observed live-search failure rather than require another redundant request; manual browser acceptance remains pending.

## Execution evidence — 2026-11-13

- Ruling: continue the existing dirty working tree, preserving all earlier integration changes and ignored runtime checks. No branch, commit, environment update or service restart was authorized or performed.
- Observed the new modeled-slow-response check fail with `ARXIV_TIMEOUT`, and metadata phase/budget assertions fail on the old 5-second read cap. After the minimal transport change all six new checks passed. The slow-response fixture models the required allowance; it does not sleep or establish live latency.
- All 28 preexisting arXiv checks passed, including actual local child watchdog termination, parent cancellation, credential-isolation, stream limits, source gate and no-retry fixtures.
- All 162 checks across ten suites passed. Syntax passed for 30 backend Python files and the new timeout script; `git diff --check` passed. Expected warning logs come from intentional invalid-result fixtures. No database concurrency suite was rerun for this timeout-only change.
- One post-change request through the local application for `scientific paper titles`, limit=10, offset=0 still returned HTTP 504 / `ARXIV_TIMEOUT` after 15.63 seconds. The running API launches fresh network children, so the extended read phase took effect without changing the parent process. This is not successful live-search acceptance and must not be reported as recovery.
- Ruling: do not widen the approved 15-second read/20-second overall limits or add retries to chase a slow upstream. Preserve the actual failure and offer local PDF upload to unblock the separate review acceptance. API/Import Worker restart and manual browser checks remain user operations.
- Independent scoped review found no blocking issue and reran all six timeout checks successfully. It confirmed the unchanged total deadline, watchdog, permits and safety limits; it did not rerun the combined suite or make live requests.
- Handoff: existing per-request network children load the updated transport. A full version-consistent restart can reuse the documented API and Import Worker commands; no frontend/Parser/database restart or configuration change is required. Do not treat restart as a cure for a slow upstream. To continue review acceptance without repeated external searches, keep API/frontend/Parser running and upload a second related text PDF manually. No paid model call, import/research submission, commit or push was performed.
