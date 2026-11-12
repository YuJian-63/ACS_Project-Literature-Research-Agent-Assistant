# MVP-3 arXiv Search and Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver keyword search, exact-version PDF import, parsing, and selection for research tasks without weakening the existing upload/evidence pipeline.

**Architecture:** Add bounded arXiv access, DB-coordinated request permits, persistent import state and an independent Import Worker. Publish Paper, provenance and import success in one DB transaction with filesystem reconciliation; reuse Parser/Runner APIs.

**Tech Stack:** Existing FastAPI/httpx/SQLAlchemy/psycopg/Alembic, PostgreSQL, React/TypeScript/Ant Design/Vite; stdlib bounded Atom parsing and supervised network processes. No provider SDK, Redis or model dependency.

**Spec:** `docs/superpowers/specs/2026-11-12-mvp-3-arxiv-search-import.md`, API contract section 10, database design section 9.

## Global Constraints

- arXiv only; versioned modern/legacy IDs <=80 characters; provider+external_id unique. No arbitrary URL/base_url or raw advanced-query input.
- q 1–200 characters/20 words; limit 1–20 default 10; offset 0–1000; Atom <=2 MiB. Title 2000, abstract 20000, authors 200x300, categories 50x64, nullable DOI 512 characters.
- Search cache: success only, TTL 600 seconds/100 pages per process; local import/parse projections refreshed on every response.
- Shared DB gate: one in-flight request, 3 seconds after completion, permit lease 120 seconds; expire+3 seconds before reclaim. Retry-After clamp 3–86400/default 60 seconds.
- Metadata total 20 seconds, PDF chain total 90 seconds, connect/read each 5 seconds, PDF <=20 MiB, at most 2 validated PDF redirects. Force-terminable child transport; no automatic retry or proxy inheritance.
- Import lease 30 seconds, heartbeat 10 seconds, total attempt 180 seconds; explicit retry CAS only; no DB locks during network I/O.
- ARXIV_ENABLED=false default; contact email required on enable; no model keys. Preserve manual duplicate uploads and old seven-table constraints. Final Paper UUID=Import UUID.
- Runtime checks stay ignored as currently practiced. Only isolated test DBs may be reset. Native PostgreSQL/live arXiv acceptance reported separately.
- No automatic branch/commit/push. Request write/network escalation under current read-only permissions.

## Review Focus

- Legacy slash IDs becoming paths/redirect injection: Task 1 normalization and transport tests.
- Cached results showing obsolete import or parser state: Task 3 API and Task 5 browser tests.
- Retry replay after the next attempt already failed accidentally triggering another download: Task 4 CAS tests.
- API and multiple Workers each applying independent throttles: Task 2 two-instance gate checks; Task 6 native-process verification.
- Old Worker or uncertain commit deleting/overwriting the winner PDF or publishing partial provenance: Task 4 completion/fencing/reconciliation tests.

## File Map

- Create `backend/src/app/arxiv.py`: strict provider models, IDs, keyword queries, Atom parsing and canonical links.
- Create `backend/src/app/arxiv_transport.py`: controlled HTTPS/streaming/redirects, child-process deadline supervision; fake transport injection only for tests.
- Create `backend/src/app/source_access.py`: shared DB permit/cooldown and bounded upstream search cache.
- Modify `backend/src/app/config.py`, `backend/.env.example`: enable flag/contact validation.
- Modify `backend/src/app/db/models.py`, `backend/sql/schema.sql`; create `backend/alembic/versions/20261112_0002_arxiv_search_import.py`: three-table additive migration and head-schema reference.
- Create `backend/src/app/paper_imports.py`: durable submission, views, retry CAS, ownership, completion/recovery.
- Create `backend/src/app/paper_import_api.py`; modify `backend/src/app/main.py`, `backend/src/app/schemas.py`, `backend/src/app/views.py`: router/types/additive nullable Paper.source.
- Create `backend/src/app/import_worker.py`; touch `backend/src/app/storage.py` only for minimal safe staging reuse.
- Create `frontend/src/pages/SearchPapersPage.tsx`; modify `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/styles.css`; existing paper components only if needed.
- Create ignored `runtime/verify-mvp-3.py`, `runtime/verify-search-browser.py` and import-process checks; extend existing ignored API/schema/browser wrappers.
- Update root/backend/frontend READMEs, API/database docs and actual execution evidence alongside delivered behavior.

## Tasks

### Task 1: Strict Provider Models and Bounded Transport

**Interfaces:** `normalize_arxiv_id(value: str) -> str`; `parse_arxiv_feed(payload: bytes) -> ArxivPage`; `ArxivClient.search(q, limit, offset) -> ArxivPage`; `ArxivClient.fetch_metadata(external_id) -> ArxivPaper`; `ArxivClient.download_pdf(external_id, destination, deadline) -> DownloadReceipt`. Provider models are Pydantic; DownloadReceipt exposes size/hash, not a client path. Client accepts the Task 2 permit interface; tests inject a fake permit/transport.

- [ ] Add checks for modern/legacy version IDs and rejection of versionless/encoded/traversal input; bounded q, safe canonical links, wrong/missing version, invalid dates/text, malformed/error XML, DTD/entities and oversized bodies.
- [ ] Run `backend/.venv/Scripts/python.exe -B runtime/verify-mvp-3.py`; observe intended missing-feature RED, not unrelated setup errors.
- [ ] Implement typed normalization/Atom parsing, fixed endpoints and supervised transport using the spec limits; disable automatic redirects/retries/trust_env.
- [ ] Add unsafe-host/path/version/port redirects, bad PDF header, misleading Content-Length, chunked >20 MiB, slow-drip/hung request and stop/owner-loss child-termination checks. Prove entire transfer deadlines, then rerun GREEN.

### Task 2: Additive Schema and Shared Provider Gate

**Interfaces:** ORM PaperSource/PaperImport/SourceRequestGate; `acquire_source_permit(sessions, provider) -> SourcePermit | None`; `release_source_permit(sessions, permit, retry_after=None) -> None`. SourcePermit carries token/deadline; seed arxiv gate in migration; use DB time and token-checked release.

Tables: `paper_sources`, `paper_imports`, `source_request_gates`, matching database design section 9.

- [ ] Add RED migration/constraint checks: version uniqueness, import state/time/error/lease combinations, positive attempts, source FK and manual-null provenance. Add two-instance gate/cooldown/token-mismatch/expiry checks.
- [ ] Create revision 20261112_0002 after 20261110_0001; do not rewrite the original revision. Add the three tables/indexes/checks and update the head-schema reference, preserving old data and constraints.
- [ ] Implement shared admission and cooldown plus bounded upstream-only cache. Verify locks are released before HTTP work; another owner cannot release a permit.
- [ ] Verify empty upgrade/downgrade and upgrade over old-schema fixtures. Downgrade refuses nonempty imports/sources. Run schema equivalence/constraint/gate checks GREEN; do not equate PGlite with native concurrency.

### Task 3: Search and Persistent Import API

**Interfaces:** section 10 Pydantic contracts; `submit_import(sessions, provider, external_id) -> dict`; `get_import(sessions, import_id) -> dict`; `retry_import(sessions, import_id, expected_attempt) -> dict`. Router paths match the API contract; source_view exposes normalized metadata/canonical links.

- [ ] Add RED API checks for disabled/contact-missing config, query bounds, bad input, actual empty vs upstream error, Retry-After, cache/local status freshness, duplicates/versions, listing/filtering/missing records and null source on manual uploads.
- [ ] Implement config/router and bounded provider search through shared permits. Refresh local projections per response; no client metadata trust or internal path/lease disclosure.
- [ ] Implement unique-key import submission and retry interface; after unique conflict, roll back and requery in a fresh transaction. Ordinary POST never retries failed records or invokes HTTP.
- [ ] Run `node runtime/verify-api.cjs` against its isolated DB; old upload/task/Mock/review checks plus new API cases must be GREEN.

### Task 4: Import Worker and Atomic Publication

**Interfaces:** `claim_import(sessions, worker_id) -> ImportJob | None`; `complete_import(sessions, job, metadata, receipt) -> bool`; `fail_import(sessions, job, code, message, retryable) -> bool`; `recover_imports(sessions) -> int`; `ImportWorker.run_once() -> bool`. ImportJob freezes import_id/provider/external_id/attempt/owner/start/deadline. Network supervision runs outside DB transactions.

- [ ] Add RED checks for persistent queue/restart, duplicate claims, exact-version metadata, no premature Paper, safe legacy filenames, complete vs shortened title and final source mapping.
- [ ] Add RED checks for retry CAS/replay after rapid second failure, stale owner/attempt/lease writes, timeout, shutdown, transaction rollback, uncertain commit and winner-file preservation.
- [ ] Implement Worker heartbeat/recovery/supervision, metadata refetch, gated PDF staging and fenced Paper+Source+success completion. Reuse storage safety without save_paper's separate commit.
- [ ] Complete explicit retry/terminal error semantics; no hidden requeue. Parser failure must remain separate from import success. Ambiguous commit retains files for reconciliation instead of redownload/deletion.
- [ ] Run focused unit/API and independent API+Import Worker+Parser process checks GREEN. Failed import has no partial Paper/Source and no Artifact/Citation.

### Task 5: Search and Import Frontend

**Interfaces:** TypeScript/Axios methods mirror API section 10; route /papers/search. Existing local-library search and task-paper selection remain intact.

- [ ] Add browser checks for explicit submit/pagination, stale response ordering, empty/disabled/429 states, safe links, duplicate-click suppression and retry replay.
- [ ] Implement page/navigation using established UI patterns; metadata is text, not HTML. Distinguish import and parsing states; show retry only for retryable failures.
- [ ] Restore server-side imports after refresh; poll pending imports every 2 seconds with cleanup, then follow Paper status. Verify cached result projections update after import success and parser failure.
- [ ] Verify imported ready papers can enter existing tasks and unready papers cannot enter real tasks; keep manual upload/Mock compatibility.
- [ ] Run `npm.cmd --prefix frontend run build` and isolated search browser wrapper GREEN; inspect desktop/mobile screenshots and prior browser regressions.

### Task 6: Acceptance and Guided Setup

- [ ] Run MVP-3, prior MVP-1B/MVP-2/API/parser regressions, frontend build, backend compile, lock consistency and git diff --check; record actual results/counts.
- [ ] Update READMEs with API/Parser/Import/Mock-or-real Runner startup and feature/contact config; mark docs implemented only after verification.
- [ ] Guide Docker Desktop startup only when ready for native PostgreSQL checks, using an isolated DB. Verify concurrent dedup/claims/provider gate, recovery and migration without resetting business data.
- [ ] Guide local contact-email setup, request network approval and perform one small live arXiv search/version-PDF import. Stop on throttling; do not repeatedly probe or present fake success as live acceptance.
- [ ] Record external blockers/limits honestly. Keep MVP-2.1 model/native evidence separate, runtime assets ignored, and all changes uncommitted until requested.

## Current Checkpoint

- [x] User approved arXiv-only search and controlled PDF import.
- [x] Inspected upload/schema/Parser boundaries and official API access/version rules.
- [x] Wrote design, proposed API/database additions and this plan.
- [ ] Detailed plan reviewed before implementation; execute inline unless instructed otherwise.
- No production code, migration or live-provider acceptance is claimed at this checkpoint.
