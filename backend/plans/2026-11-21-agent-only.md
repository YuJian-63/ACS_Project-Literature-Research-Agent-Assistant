# Agent-only backend cleanup

Goal: execute all new research through the independent Agent; only change backend files.

Design: remove local LangGraph and mock execution, preserve Agent protocols and historical records, and extract PDF metadata without generating backend chunks.

## Implementation plan

- [x] Add regressions for Agent-only execution and PDF metadata extraction.
- [x] Remove legacy execution paths while preserving authorization, idempotency and recovery.
- [x] Stop PDF chunk generation and persistence.
- [x] Remove obsolete modules, dependencies and retired tests.
- [x] Update backend documentation and configuration examples.
- [x] Verify unit tests, isolated PostgreSQL and backend-only changes.

## Verification ledger

- Baseline: 302 tests, 113 skipped, 2 failures and 1 error. Existing failures: the Agent deploy archive test and both process roundtrip tests. Agent runtime files including agent_io are missing, outside this change's scope.
- Keep historical database structures, including paper_chunks, to avoid deleting historical evidence. No migration or live database modification is needed.
- Work on the existing backend-dev-v2 branch. Do not commit, push, deploy, or modify secrets.

## Final verification (2026-11-21)

- Backend-only changes confirmed, including new tests, this plan, configuration example and README. Agent, frontend, root documentation, real .env files and existing databases were not modified. No commit, push or deployment was performed.
- Final full suite on an isolated PostgreSQL 17 container: 235 tests, 231 passed, 3 failures and 1 error, no skips. Dedicated ownership, authentication, Agent and migration databases were created for this run; the temporary container was removed afterwards.
- All newly added Agent-only, PDF metadata, archived-chunk preservation and retired-runner tests passed. Existing dispatch recovery still preserves dispatch identity and the original start/deadline. The historical result endpoint and native Agent citation tests passed.
- The three Agent packaging/process failures also occurred in the pre-change unit baseline: required independent Agent runtime files, including agent_io, are absent. Those tests and Agent files were left unchanged.
- Enabling PostgreSQL coverage additionally exposed an existing ownership login test that registers RegisteredUser but signs in as registereduser and expects success. Its method body is identical to HEAD; current authentication intentionally requires matching case. Authentication implementation and this unrelated expectation were left unchanged.
- Static checks: changed Python files passed Ruff F821/F401; all backend source/test files parsed successfully; git diff --check passed.
- Dependency verification: uv lock --check --offline passed (35 packages); frozen production requirements export passed. Compared retained lock entries against HEAD: all 34 external package versions, markers, URLs and hashes are unchanged. Removed 28 orphan packages and the direct LangGraph dependency; no unrelated dependency upgrade.
- Local test interpreter: Python 3.13.9. ECS Python 3.12, real models, browser flows and live TACC were not exercised in this cleanup.

## Operational compatibility

- Only TASK_RUNNER=agent is accepted. Existing deployments using mock/langgraph must update that setting and stop retired workers before upgrading.
- Existing python -m app.runner_worker remains the Agent worker entrypoint. Dispatch still requires AGENT_DISPATCH_ENABLED=true and valid manual/local/TACC configuration; it is not auto-enabled.
- Parser readiness now describes PDF/metadata validation, not full-text extraction. Titles/page counts remain available; blank/scanned PDFs may be ready for the Agent to evaluate.
- Existing paper_chunks and legacy task/citation schema are archival compatibility. No new backend chunks are generated, and no destructive schema migration was added.
- Pending legacy mock/langgraph tasks become RUNNER_RETIRED through the monitor. Terminal historical tasks, artifacts and citations remain readable.
