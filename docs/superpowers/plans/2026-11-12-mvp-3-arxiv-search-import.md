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

- [x] Add checks for modern/legacy version IDs and rejection of versionless/encoded/traversal input; bounded q, safe canonical links, wrong/missing version, invalid dates/text, malformed/error XML, DTD/entities and oversized bodies.
- [x] Run `backend/.venv/Scripts/python.exe -B runtime/verify-mvp-3.py`; observe intended missing-feature RED, not unrelated setup errors.
- [x] Implement typed normalization/Atom parsing, fixed endpoints and supervised transport using the spec limits; disable automatic redirects/retries/trust_env.
- [x] Add unsafe-host/path/version/port redirects, bad PDF header, misleading Content-Length, chunked >20 MiB, slow-drip/hung request and stop/owner-loss child-termination checks. Prove entire transfer deadlines, then rerun GREEN.

### Task 2: Additive Schema and Shared Provider Gate

**Interfaces:** ORM PaperSource/PaperImport/SourceRequestGate; `acquire_source_permit(sessions, provider) -> SourcePermit | None`; `release_source_permit(sessions, permit, retry_after=None) -> None`. SourcePermit carries token/deadline; seed arxiv gate in migration; use DB time and token-checked release.

Tables: `paper_sources`, `paper_imports`, `source_request_gates`, matching database design section 9.

- [x] Add RED migration/constraint checks: version uniqueness, import state/time/error/lease combinations, positive attempts, source FK and manual-null provenance. Add two-instance gate/cooldown/token-mismatch/expiry checks.
- [x] Create revision 20261112_0002 after 20261110_0001; do not rewrite the original revision. Add the three tables/indexes/checks and update the head-schema reference, preserving old data and constraints.
- [x] Implement shared admission and cooldown plus bounded upstream-only cache. Verify locks are released before HTTP work; another owner cannot release a permit.
- [x] Verify empty upgrade/downgrade and upgrade over old-schema fixtures. Downgrade refuses nonempty imports/sources. Run schema equivalence/constraint/gate checks GREEN; do not equate PGlite with native concurrency.

### Task 3: Search and Persistent Import API

**Interfaces:** section 10 Pydantic contracts; `submit_import(sessions, provider, external_id) -> dict`; `get_import(sessions, import_id) -> dict`; `retry_import(sessions, import_id, expected_attempt) -> dict`. Router paths match the API contract; source_view exposes normalized metadata/canonical links.

- [x] Add RED API checks for disabled/contact-missing config, query bounds, bad input, actual empty vs upstream error, Retry-After, cache/local status freshness, duplicates/versions, listing/filtering/missing records and null source on manual uploads.
- [x] Implement config/router and bounded provider search through shared permits. Refresh local projections per response; no client metadata trust or internal path/lease disclosure.
- [x] Implement unique-key import submission and retry interface; after unique conflict, roll back and requery in a fresh transaction. Ordinary POST never retries failed records or invokes HTTP.
- [x] Run `node runtime/verify-api.cjs` against its isolated DB; old upload/task/Mock/review checks plus new API cases must be GREEN.

### Task 4: Import Worker and Atomic Publication

**Interfaces:** `claim_import(sessions, worker_id) -> ImportJob | None`; `complete_import(sessions, job, metadata, receipt) -> bool`; `fail_import(sessions, job, code, message, retryable) -> bool`; `recover_imports(sessions) -> int`; `ImportWorker.run_once() -> bool`. ImportJob freezes import_id/provider/external_id/attempt/owner/start/deadline. Network supervision runs outside DB transactions.

- [x] Add RED checks for persistent queue/restart, duplicate claims, exact-version metadata, no premature Paper, safe legacy filenames, complete vs shortened title and final source mapping.
- [x] Add RED checks for retry CAS/replay after rapid second failure, stale owner/attempt/lease writes, timeout, shutdown, transaction rollback, uncertain commit and winner-file preservation.
- [x] Implement Worker heartbeat/recovery/supervision, metadata refetch, gated PDF staging and fenced Paper+Source+success completion. Reuse storage safety without save_paper's separate commit.
- [x] Complete explicit retry/terminal error semantics; no hidden requeue. Parser failure must remain separate from import success. Ambiguous commit retains files for reconciliation instead of redownload/deletion.
- [x] Run focused unit/API and independent API+Import Worker+Parser process checks GREEN. Failed import has no partial Paper/Source and no Artifact/Citation.

### Task 5: Search and Import Frontend

**Interfaces:** TypeScript/Axios methods mirror API section 10; route /papers/search. Existing local-library search and task-paper selection remain intact.

- [x] Add browser checks for explicit submit/pagination, stale response ordering, empty/disabled/429 states, safe links, duplicate-click suppression and retry replay.
- [x] Implement page/navigation using established UI patterns; metadata is text, not HTML. Distinguish import and parsing states; show retry only for retryable failures.
- [x] Restore server-side imports after refresh; poll pending imports every 2 seconds with cleanup, then follow Paper status. Verify cached result projections update after import success and parser failure.
- [x] Verify imported ready papers can enter existing tasks and unready papers cannot enter real tasks; keep manual upload/Mock compatibility.
- [x] Run `npm.cmd --prefix frontend run build` and isolated search browser wrapper GREEN; inspect desktop/mobile screenshots and prior browser regressions.

### Task 6: Acceptance and Guided Setup

- [x] Run MVP-3, prior MVP-1B/MVP-2/API/parser regressions, frontend build, backend compile, lock consistency and git diff --check; record actual results/counts.
- [x] Update READMEs with API/Parser/Import/Mock-or-real Runner startup and feature/contact config; mark docs implemented only after verification.
- [x] Guide Docker Desktop startup only when ready for native PostgreSQL checks, using an isolated DB. Verify concurrent dedup/claims/provider gate, recovery and migration without resetting business data.
- [x] Guide local contact-email setup and the user-run, authorized small live arXiv search/version-PDF import. Stop on throttling; do not repeatedly probe or present fake success as live acceptance.
- [x] Record external blockers/limits honestly. Keep MVP-2.1 model/native evidence separate, runtime assets ignored, and all changes uncommitted until requested.

## Current Checkpoint

- [x] User approved arXiv-only search and controlled PDF import.
- [x] Inspected upload/schema/Parser boundaries and official API access/version rules.
- [x] Wrote design, proposed API/database additions and this plan.
- [x] Detailed plan reviewed before implementation; execute inline unless instructed otherwise.
- Tasks 1-6 are complete for the agreed MVP-3 scope. On 2026-11-13 the user supplied passing native PostgreSQL migration/eight-group acceptance output, live arXiv search/import/parse output and confirmation of browser/Mock-task acceptance (records below). This is user-run acceptance evidence, not an independent agent rerun. Real model integration remains separate MVP-2.1 work.


## Execution Record — 2026-11-12

- Planning baseline committed first as `d66aa45 docs: plan arXiv search and paper import`; implementation remains uncommitted, no push.
- Task 1: 28 provider/transport checks GREEN, including real child protocol with local HTTP fake, own watchdog without parent supervision, forced timeout/cancel, bounded bytes, redirects, and minimal environment. No external source request.
- Tasks 2-4: 31 isolated PGlite checks GREEN. Includes additive migration over old data, safe downgrade, ORM drift, shared permit/cooldown/expiry, cache, API projection, retry CAS/replay, exact-version failure, Worker/Parser linkage, stale ownership, timeout, atomic publication, rollback winner protection and uncertain-commit retention/recovery.
- Existing API: 24 checks GREEN plus independent Uvicorn/Mock Worker persistence/restart/recovery. Existing MVP-1B 14 and MVP-2 15 checks GREEN; backend bootstrap 12 GREEN.
- Schema: reference DDL = generated head migration = ORM (111 columns, 179 constraints, 40 indexes including unique); offline downgrade and 18 online Alembic/ORM checks GREEN on isolated PGlite.
- Task 5: Chromium search checks GREEN: explicit search/paging, stale ordering, safe metadata/links, duplicate-click suppression, expected_attempt replay after lost response and rapid repeat failure, persisted history/polling, parser failure, empty/disabled/429, desktop/390px screenshots inspected.
- Independent browser -> Vite -> API -> Import Worker -> Parser subprocess -> ready Paper/Source -> library provenance -> existing task selection -> Mock artifact GREEN. arXiv is a deterministic fixture and DB is PGlite.
- Prior browser regressions GREEN: manual upload/Mock task/reload/budget failure; Parser ready/failure and preserved task draft; review table/row-owned citations/rerun/budget failure with local fake model; existing mocked UI fault checks.
- Frontend typecheck/production build, PDF core/parser termination, 33 backend Python syntax checks, offline locked dependency check (58 packages), ignored runtime/.env/storage checks and git diff whitespace checks passed. Generated scripts/screenshots/logs stay ignored under runtime, following the existing project practice; formal test/CI migration remains MVP-2.1 work.
- Ruling: PostgreSQL ID CHECK regex uses capturing groups so SQLAlchemy text does not interpret `:0` inside noncapturing groups as a bind parameter. Original migration is unchanged.
- Ruling: reject encoded HTTP bodies and oversized Location/Retry-After headers; do not truncate security-sensitive redirects. Child process inherits only OS launch/temp variables and a fixed source PYTHONPATH, not model/DB/proxy credentials.
- Review fixes verified RED -> GREEN: rollback cleanup reacquires Import row lock and checks attempt/owner/no Paper; commit reconciliation locks the identity; initial gate wait is outside the network phase budget but inside the 180-second attempt; subsequent redirect gate waits share the same 90-second PDF phase; the fetch child enforces its own hard wall-clock watchdog.
- External prerequisites checked: Docker Desktop Linux engine pipe is unavailable; `backend/.env` does not exist. No email was invented and no local secrets were printed in the handoff. User must start Docker Desktop, then use an isolated native PostgreSQL acceptance DB; configure their own contact email locally before one small approved live arXiv search/import. Do not reset business data or equate offline evidence with these remaining checks.
- Full setup and worker startup guidance is in backend/README.md section 9. MVP-2.1 real model/native evidence is still separate and pending.

## Guided Native Acceptance — 2026-11-13

- Evidence: user supplied command output from the same guided PowerShell session; these results were not independently rerun by the agent. Docker Engine 28.5.1 / Compose 2.40.2; dedicated project `acs-mvp3-acceptance-e379b08d`, loopback port 55432, separate named volume and database/user `literature_acceptance` on native PostgreSQL 17.6.
- User ran both Alembic upgrades to head `20261112_0002`, `alembic current`, `alembic check` (no new operations), and `psql \\dt` showing the expected 11 tables. No business database was migrated or cleared.
- User ran ignored `runtime/verify-mvp-3-native.py` against that dedicated empty database. All eight groups passed: target guards; four-process submit deduplication; actual row-lock/SKIP LOCKED claims; retry CAS/replay/stale attempts; atomic rollback/concurrent completion/winner bytes; concurrent expired-lease recovery without hidden retries; shared source gate/token/cooldown/Retry-After; expired-permit grace/stale-owner protection.
- Script reported `NATIVE ACCEPTANCE PASSED: 8 groups; no arXiv/model requests.` and successful cleanup of only its fixture rows/files, preserving the schema. It does not TRUNCATE or DROP tables and refuses nonempty business tables or a non-acceptance connection target.
- Scope: native evidence covers these eight targeted groups, not every previous PGlite fault injection, native old-data migration scenario, real model integration or live upstream HTTP. Existing 2026-11-12 evidence remains historical and is not relabeled as native.
- The live-source and final browser gates were subsequently completed in the guided session below. No business rows or downloaded acceptance PDF were removed by this documentation update.

## Guided Live and Browser Acceptance — 2026-11-13

- Evidence: command outputs and manual confirmations supplied by the user in the guided session; the agent did not independently rerun these requests or inspect the live browser. Local contact email and database credentials remain in ignored configuration and are omitted here. The new-terminal configuration check returned arXiv configured=true and Runner=mock; API `/health` returned ok and `/ready` returned ready.
- One live search used q=`attention is all you need`, limit=1, offset=0. The response reported total=134 and returned arXiv `2512.19700v1`, titled `"All You Need" is Not All You Need for a Paper Title: On the Origins of a ScientificMeme`. This is keyword matching, not an exact-title lookup for the original attention paper. The search result initially had no local import or Paper.
- Submitting that exact version created import `a85d3a28-6810-4ed0-b66e-61d3f7fc5f1b`; a repeated POST returned the same ID, attempt=1, status=queued. A separate GET returned that record before the Import Worker was started.
- The independent Import Worker changed the record to succeeded at attempt=1, with Paper ID `a85d3a28-6810-4ed0-b66e-61d3f7fc5f1b`, paper_status=uploaded and error=null. User output reported started_at=`2026-11-12T17:02:34.032726Z` and finished_at=`2026-11-12T17:02:38.678793Z` (UTC; the local Asia/Shanghai session date was November 13).
- The independent Parser Worker then produced ready, page_count=9, parser_version=`pypdf-7.0.1-text-v1`, size_bytes=1121039 and error=null. Reported SHA-256: `e547d220338713fedba09803daccb05a7f023a198d172f585611a3c82f71d89f`. Source provider/external_id and canonical abstract/PDF links all matched `arxiv` / `2512.19700v1`.
- User confirmed frontend startup, import-history refresh recovery, library provenance/page count, and opening the saved local PDF from its title were all normal. From the import history, the research shortcut preselected the imported Paper; the default summary task completed through the independent Mock Worker.
- Mock task ID: `92bada43-5467-4f54-982b-8844c5ecc1f1`. User confirmed automatic Paper selection, task success, mock labeling/result/execution records and browser refresh recovery were all normal. This establishes the application flow, not genuine model analysis or paper conclusions.
- Scope: one actual search and one exact-version PDF import/parse on the dedicated native database, plus user-confirmed browser and Mock-task persistence. Actual upstream throttling, malicious redirects and network faults were not manually induced; their prior fixture checks remain separate. No model API request or real-model quality acceptance is claimed. Formal tests/CI and real-model acceptance remain MVP-2.1 follow-up work. Implementation and this acceptance record remain uncommitted until requested.
