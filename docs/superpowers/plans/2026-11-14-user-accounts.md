# User Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkboxes for tracking.

**Goal:** Implement username/password signup with email verification/recovery and complete private user libraries.
**Architecture:** FastAPI authenticated dependencies, PostgreSQL sessions and encrypted mail outbox; user ownership enforced at service and composite database boundaries; React authenticated shell.
**Tech Stack:** Existing Python/SQLAlchemy/PostgreSQL/React/Ant Design, argon2-cffi and cryptography.
**Spec:** docs/superpowers/specs/2026-11-14-user-accounts-design.md

## Global Constraints

No branch creation/commit/push without user request. Work in current checkout; disjoint delegate write scopes. User authorized removing old application data; verify target first and never delete databases/schema or unrelated files. Never print credentials or send real mail in automated tests. No anonymous compatibility for business APIs. Username login remains; email is required and verified. Keep automatic review budgets, idempotency and worker fences. No real model/arXiv calls in tests.

## Review Focus

Cross-user IDs/counts/PDF/exports and cache annotations; reset/login/token races; mail restart/retry and secret redaction; logout plus stale client responses; migration refusing populated old schemas. Cover these in backend/PostgreSQL and browser checks.

## Tasks

- [x] 1. Safe reset + persistence: add account models, strict owner foreign keys/indexes, migration 0004 and config; provide guarded application-data reset CLI. Inspect configured database and storage without secrets, perform only authorized project cleanup when safe. Tests: fresh/old migration, composite FK cross-owner rejection, reset scope.
- [x] 2. Auth backend/mail: app/auth/{security,service,dependencies,api,mail}.py plus mail_worker.py and tests/test_auth.py. Public signup/confirmation/login/logout/me/recovery/change password, Origin/CSRF, database limits, encrypted durable SMTP outbox with lease/retry. Interfaces use app.db.models.User/AuthSession/AuthEmailToken/AuthMailOutbox/AuthRateBucket and Settings keys in spec. require_user(request) returns authenticated User; require_user guards mutations too; user response includes csrf_token. No edits to local-owned models/config/main/business files.
- [x] 3. Ownership integration: API papers/tasks/imports and domain storage/task/import service enforce explicit user_id, user-local idempotency and source identities, user quotas. Import worker inherits owner from row, source gates/cache remain shared. Integrate router, safe validation error redaction, CORS and private cache headers.
- [x] 4. Frontend auth: new auth provider/pages, client cookies/CSRF, protected routes and account menu, bilingual forms, mail fragment confirmation/reset and state cleanup with identity generation/cross-tab notification. Ownership never supplied by UI. Preserve existing workspace and language. Use POST schemas from spec and /auth/me shape {user:{id,username,email},csrf_token}.
- [x] 5. Verification + operation: isolated PostgreSQL tests for two users, tokens/concurrency/quotas and mail leases, unit tests, frontend build/browser flows; update API/database/backend/frontend docs and sanitized env. QQ real email and user-side production SMTP setup documented separately; do not invent real acceptance. Review patch, resolve findings, report exact remaining configuration.

## Execution ledger

2026-11-14: Design approved. Ruling: user authorized data deletion, replacing legacy owner migration; migration fails before changes if old business tables remain populated. Existing main checkout retained because no branch/worktree creation was authorized; no automatic commit. Secrets and actual .env remain untracked.

2026-11-14: Verified intended existing Docker PostgreSQL17 container and configured literature_acceptance/storage paths. Dry-run counted 11 papers, 33 tasks, 11 PDF files; old populated-schema migration refused as intended. Guarded reset completed, preserving alembic_version/schema; upgrade0004 and alembic check passed. New isolated ownership_tests and review_tests run on native PostgreSQL17: 11 ownership/auth integration tests and 8 staged review regressions passed. Frontend build/typecheck, review verifier and mocked auth browser flows passed. Local ignored .env received three generated independent auth/encryption keys without displaying values. SMTP credentials remain unconfigured; no real email or model requests sent.

2026-11-14 Final verification: auth harness 74/74 (native concurrency included), ownership native16/16, staged-review native8/8, default discovery124 (68 passed,56 separately gated). Build/typecheck, review UI verifier and mocked auth browser suite passed. Final review fixed reset gate seed loss (positive reset test RED→GREEN), stale rate cleanup (native refreshed-bucket race), and import completion/retry foreign-key deadlock (test_import_completion_does_not_deadlock_with_retry_quota_lock RED→GREEN; FOR NO KEY UPDATE preserves quota serialization). Reference SQL vs ORM types/defaults and seed verified on native PostgreSQL. Configured database remains head0004, business/users/files zero, source seed1. Automatically created test databases cleaned. No commits or pushes.

Final minor (deferred): frontend email/reserved-username prevalidation is looser than server validation; server remains authoritative.
Final minor (deferred): login/current-password client validation requires15 characters while server accepts1; valid registered passwords always require15.
Final minor (deferred): verification waiting copy says24h while server TTL can be shortened; default24h verified, email itself uses configured TTL.

Pending manual acceptance: fill private QQ SMTP_USERNAME/SMTP_FROM/SMTP_AUTH_CODE in existing ignored backend/.env, then verify actual bilingual mail delivery and links. No real email has been sent; no credentials were requested in chat. Independent signing/encryption keys were generated and saved locally without printing values.
