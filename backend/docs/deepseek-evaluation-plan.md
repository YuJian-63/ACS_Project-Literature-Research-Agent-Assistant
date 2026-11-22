# DeepSeek research evaluation

Approved scope: implement backend-only, asynchronous evaluation of accepted Agent results. Agent and frontend code remain unchanged. Evaluation must never change the research outcome or overwrite its answer.

## Rubric research-v1

Each dimension is scored from 0 to 5: grounded correctness 30%, citation support 30%, task completion 20%, analysis quality 15%, clarity 5%. Zero means absent or fundamentally wrong; 1 severe deficiencies; 2 partial with substantial deficiencies; 3 adequate with identifiable gaps; 4 strong with minor gaps; 5 excellent within the available evidence. The backend computes the weighted score out of 100 using decimal arithmetic. An insufficient-evidence assessment has no overall score.

Summary checks cover motivation, method, findings and limitations. QA checks the question and subquestions, evidence and acknowledged unknowns. Review checks source coverage, synthesis, contradictory findings and comparable experimental conditions. Length, citation counts and tool counts do not earn points. Completed and useful partial results are eligible. Failed/empty results are skipped, not scored zero. Evaluation explanations follow the question's language.

## Architecture

Use a durable PostgreSQL queue and a separate backend worker. Synchronous scoring would delay result delivery and couple research availability to DeepSeek. In-process background tasks would lose work on API restarts. The durable worker uses bounded attempts, expiring leases and fenced completion; transactions never span external calls. A result and its pending evaluation commit atomically. The feature defaults off; historical tasks are evaluated only by explicit authenticated request.

The immutable input includes task type/question, native answer/comparison, all native citations/sources, mapped display citation keys, stop reason and unresolved items. This retains external citations omitted from the display table. The worker optionally checks authorized, hash-verified local PDF pages in a bounded subprocess; this does not restore LangGraph or paper_chunks. Missing pages, external originals and extraction limits are disclosed. Original context and its digest are retained for audit. Agent excerpts alone produce evidence_only scope, never a claim of independently verified factual accuracy.

DeepSeek receives untrusted research JSON, an evaluation-only system instruction, a bounded JSON-output request and no tools. Strict models reject unknown fields, invalid scores/references and non-finite values. Input overflow fails explicitly. Response sizes and retry counts are bounded. Keys and raw provider errors are never stored or returned. Reports contain rationales, issue locations, suggestions, scope, limitations, versions, model and usage.

## Storage and API

Add task_evaluations with input/config digests and snapshots, status, report, attempt/lease/retry metadata, usage, error code and timestamps. Unique task/input/config identity makes requests idempotent; changed input or rubric/model configuration creates a new version. Task/artifact foreign keys cascade deletion. Existing ownership and session/CSRF enforcement apply to GET/POST /api/v1/tasks/{task_id}/evaluation. GET returns not_requested when absent and can select an evaluation ID belonging to that task. POST reuses active/completed records and can retry failures within their attempt budget. A per-user daily evaluation-version allowance and per-version attempt budget bound requests; queued attempts can run on subsequent days. Existing frontend contracts remain unchanged.

## Implementation and verification

1. Strict rubric/report models with regression fixtures for weighting, insufficient evidence and fabricated references.
2. Model/Alembic migration, durable enqueue/claim/finish, ownership and cascade tests.
3. Bounded evidence subprocess and HTTP-mocked DeepSeek adapter, response validation and redaction tests.
4. Atomic automatic enqueue, worker recovery, backoff and stale-owner fencing.
5. Authenticated APIs, example configuration and operating/systemd guidance under backend/.
6. Backend suite and isolated PostgreSQL upgrade/check/downgrade verification, then scoped code review. No live model calls or production changes.

## Decisions and verification ledger

- Use the existing clean backend-dev-v2 checkout; no branch/commit/push requested.
- Reuse httpx/PostgreSQL; no SDK or broker required.
- DeepSeek model is configurable; credentials are provided by the operator. No paid requests during implementation.
- Added revision 20261122_0014 after the existing 0013 head, plus the matching reference SQL. Isolated PostgreSQL 17 validation covers upgrade/check/downgrade/re-upgrade and preservation of existing research during evaluation-only downgrade.
- The judge receives the original user question, not the Agent's English instruction wrapper. All native citations are retained; paths and API credentials are excluded from judge input. Configuration, research and evidence snapshots are checked against their digests before external calls.
- 2026-11-22: all 33 evaluation-specific tests passed, including mocked full worker execution, ownership/real session CSRF, concurrent claims, lease exhaustion/fencing, frozen evidence retries, source hashes, extraction timeout/secret isolation, output validation and slow partial-response timeout handling.
- Independent review identified deletion-based allowance refunds, a user-lock upgrade deadlock risk and permanently quota-skipped records. All three were reproduced with PostgreSQL tests before fixing. Allowance now lives in independent UTC daily quota rows, remains consumed after task deletion, avoids user-row lock upgrades and permits explicit re-request after quota recovery. The migration and reference SQL include this additive quota table.
- Final backend run with isolated Agent, authentication, ownership and migration databases: 291 tests, 288 passed, three pre-existing failures. The same three failures were reproduced against unchanged HEAD backend sources: two Agent process integration cases (missing agent_io.job) and a POSIX file-mode assertion on Windows. No frontend or Agent files were changed to address them.
- Independent focused re-review accepted the quota/locking/recovery fixes and found no remaining important or blocking issues. The temporary test PostgreSQL instance is isolated from ECS and no live model calls were made.
- Optional backend/ops/acs-evaluation.service participates in the existing research runner's stop/start lifecycle. It has not been installed in production. No real DeepSeek request, frontend integration, git commit/push or ECS deployment was performed.
