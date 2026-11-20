# v3 Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Preserve the accepted v3 UI and auth/search/library, remove legacy three-category workflows and simulations, and start with an independent empty v3 database and file store.

**Architecture:** A separately named PostgreSQL container, volume, role and database; v3-only environment, session cookie, ports and storage. A fresh v3 migration contains accounts, paper library/imports and a unified research model. Agent execution stays unconnected; no fallback to legacy LLM workflows or v2 data.

**Tech Stack:** React, FastAPI, SQLAlchemy/Alembic, PostgreSQL 17, Docker Compose.

**Spec:** User selected preservation of current v3 UI, login, search and library, with removal of legacy research/simulation remnants.

## Constraints

- Do not edit, migrate, reset or stop v2's database, storage or backend.
- Preserve a private local checkpoint before cleanup. Do not publish credentials or old local data.
- Do not copy v2 users, papers, sessions or tasks into v3.
- Keep the existing `agent/` source intact for later integration.
- No Git commit/push until the user's requested review/upload step is authorized.

## Tasks

- [x] Snapshot current v3 code/config/test results and inspect cross-version dependencies.
- [x] Remove old frontend research pages/components/types and standalone fictional prototypes; retain and relocate shared evidence/progress/style helpers.
- [x] Remove legacy research executors, task APIs/models and simulation stores/routes/importers.
- [x] Keep accounts/papers/imports; introduce one category-free research model and read/delete API. Leave actual execution unavailable.
- [x] Replace old migrations with a fresh v3 initial schema, runnable only against the new database.
- [x] Configure v3-only PostgreSQL container/volume/credentials, local auth keys/cookie, API/UI ports and storage; use its own Python environment.
- [x] Start v3 independently, initialize the empty schema and verify account/library/search plumbing without copying old data.
- [x] Run build, backend/API/migration/browser isolation checks; verify v2's code, database and files remain untouched.
- [x] Replace stale setup/handoff docs with the final v3 architecture and commands.

## Review focus

Fresh database defaults and migration guards; cross-version cookies/local storage; paper deletion under new research references; parser/import lease utilities formerly imported from old tasks; stale tests/docs that invoke legacy execution or shared configuration.

## Completion notes

- Independent PostgreSQL container/volume on 55435 and fresh schema `v3_0001`; v3 service/UI ports 8002/5175.
- The initial bulk cleanup was rejected by automatic review. The safer sequence created a private checkpoint and independent database, extracted shared parser/import lease utilities, proved retained imports, applied/checked the new schema, then retired explicitly superseded assets.
- User approved copying only mail/arXiv provider settings; no data, sessions or auth keys were copied.
- Final fresh-context review found URL-query target overrides and an old default storage layout; both were reproduced, fixed and regression-tested.
- Tests: 90 discovered unit checks (34 intentionally skipped without a temporary DB), 75 native authentication checks, one comprehensive temporary-PostgreSQL integration case, three intercepted browser suites and live unauthenticated login/proxy checks.
- V2 source/workspace remains clean; its original user/paper/task counts and all eight PDF hashes were checked read-only. V3 business tables and PDF directory remain empty.
- The user subsequently authorized uploading this completed version to `frontend-dev-v3`; source and documentation may now be committed/pushed, excluding private configuration and runtime data.
