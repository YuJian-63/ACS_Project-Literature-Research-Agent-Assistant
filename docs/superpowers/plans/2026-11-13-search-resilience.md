# Search resilience implementation plan

**Spec:** `docs/superpowers/specs/2026-11-13-search-resilience.md`

**Execution:** Inline in the existing workspace. Preserve all preexisting dirty changes and ignored runtime-test conventions. No network experiments, database mutations, model calls or Git writes.

## Tasks

### 1. Safe backend diagnostics

Files: `backend/src/app/{arxiv,arxiv_transport,source_access,paper_import_api}.py`, `runtime/verify-search-resilience.py`.

- [x] Add offline failing checks for transport phases, child protocol propagation/validation, source/status phases and redacted request-correlated API logs.
- [x] Add allowlisted internal phases and bounded logging without changing error envelopes or request/security budgets.
- [x] Run new checks and existing arXiv timeout/transport checks.

### 2. Frontend result retention and cooldown

Files: `frontend/src/pages/SearchPapersPage.tsx`, `runtime/verify-search-resilience-ui.py`.

- [x] Add and run failing browser checks with all API calls intercepted and no real provider/model requests.
- [x] Keep snapshot provenance separate from attempted query/offset; retain exact retry and snapshot pagination semantics.
- [x] Add guarded five-second timeout wait without extending import cooldown; preserve latest-request fencing.
- [x] Run new and existing search browser regressions and frontend typecheck/build.

### 3. Documentation and review

Files: `backend/README.md`, `frontend/README.md`, `docs/api-contract.md`, this plan.

- [x] Document diagnostic fields, snapshot lifetime and manual retry behavior, explicitly separating resilience from live-search recovery.
- [x] Run combined backend regressions, syntax and whitespace checks; review the scoped diff for privacy, fencing and compatibility.
- [x] Record measured results and service reload guidance without restarting user services or claiming restored external search.

## Review focus

- Failed query B or page N must not label snapshot A/page M as its own result; retry B/N while pagination still targets A/M.
- Enter and direct pagination handlers must honor absolute cooldowns, not just disabled presentation.
- 429 cooldown remains shared; timeout wait does not block import/history actions or auto-submit when it expires.
- Cancelled/obsolete success and failure cannot overwrite current results or impose cooldown.
- Child-controlled diagnostic data must not enter logs outside the allowlist; all existing request, stream and process guards remain in force.

## Ledger

- Ruling: reuse the current dirty workspace rather than create a branch/worktree, preserving ongoing accepted integration work and the user's running environment. Runtime tests follow the existing ignored-script convention.
- Ruling: five seconds is a UI-side manual search wait, not a new backend quota or an assertion that the provider recovers after five seconds. Clients outside this page still rely on existing backend source permits.
- Ruling: status-enrichment failures belong to the history area; source success clears the loading indicator immediately, so a freshly received snapshot is never described as old while enrichment is pending. Browser assertions first reproduced both the failure and the pending-state mislabel before their fixes.
- Ruling: watchdog exit 124 is the child's established deadline signal. A new failing protocol check justified mapping it to `ARXIV_TIMEOUT` / `deadline`; other abnormal exits retain validation failure.

## Execution evidence — 2026-11-13

- The initial eight diagnostic tests failed on missing phase propagation and logs. They passed after implementation; subsequent watchdog and HTTP-boundary checks brought the suite to ten, all passing.
- The browser test first failed because a timed-out page cleared the previously successful page. It now passes retention/provenance, pending visibility, exact-offset retry, snapshot-owned paging after a different query fails, timeout handler bypass attempts, independent imports/history, 429 shared cooldown, no automatic retry, stale request fencing, empty results, first failure and reload cases. All APIs were intercepted; nonlocal browser requests were blocked. The isolated Vite target pointed at unused local port 1, not the user's backend.
- The new browser scenarios and existing `verify-search-ui.py` both passed on the final frontend version. Desktop (1440px) and mobile (390px) screenshots were inspected, with no horizontal overflow; existing page styling was preserved.
- All 172 checks across eleven backend suites passed, including ten new diagnostic checks and existing arXiv subprocess/deadline/security checks. Intentional invalid-result fixtures emit expected warnings. No database concurrency suite was rerun because schema and locking behavior were unchanged.
- Final `npm.cmd run build` passed TypeScript checks and production build. Syntax parsing passed for 32 Python files. `git diff --check` passed. Scoped local code review found and resolved the enrichment labeling issues; no independent agent review was requested or performed.
- The optional design context launcher could not initialize its external cache. Existing source/styles were inspected directly; no tool install or permission request was needed.
- No external arXiv requests, model calls, database/data changes, user-service restarts, commits or pushes occurred in this iteration. Live-search recovery remains unverified.

## Apply and inspect

Restart the API in its existing terminal (`Ctrl+C`, then `uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000` from `backend`) to load API logging and updated error types. Refresh the frontend if Vite is already running; otherwise use `npm.cmd run dev` from `frontend`. No database migration is needed. An already-running Import Worker can be restarted at an idle boundary to load the same transport version; Parser and research Runner need no changes for search resilience. Service restart is deployment of these changes, not evidence that external search is fixed.
