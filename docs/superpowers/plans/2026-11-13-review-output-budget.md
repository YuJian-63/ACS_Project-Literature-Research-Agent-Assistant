# Review output budget implementation plan

**Spec:** `docs/superpowers/specs/2026-11-13-review-output-budget.md`

**Execution:** Inline in the current workspace, preserving existing dirty changes. Use the existing ignored runtime-test convention; no Git writes, service restarts, model calls or database changes.

## Tasks

### 1. Frozen cap and compatibility

Files: `backend/src/app/tasks.py`, `backend/src/app/runner_worker.py`, `runtime/verify-review-output-budget.py`.

- [x] Add failing submission, loader and worker tests for new 4096 review caps, historical 2048 caps and strict stored-value validation.
- [x] Freeze the server-owned cap on new real reviews, carry it into ResearchJob with a legacy default and apply it without bypassing remaining budget.
- [x] Verify replay, unchanged summary/QA/Mock behavior, narrow and exhausted budgets, one-call HTTP payload, all-empty zero-call and truncated-output nonpublication.

### 2. Documentation and regression

Files: `backend/README.md`, `docs/api-contract.md`, this plan.

- [x] Update current output-limit descriptions and distinguish the earlier 2048 acceptance boundary from the new frozen cap.
- [x] Run focused and combined backend regressions, syntax/whitespace checks and a scoped local review.
- [x] Record results and manual API/Runner restart instructions; keep live model acceptance pending.
- [x] Record the subsequent user-reported successful two-paper review and manual acceptance separately from offline verification.

## Review focus

- Missing frozen cap, including review-v2 tasks, must never acquire 4096 merely by restarting Worker.
- Booleans, floats, strings, unsupported integers and single-paper 4096 must fail before model creation.
- 4096 is not added on top of the remaining total budget; just-below and just-above exhaustion must be exercised.
- JSON truncation and invalid citations still fail without retries or publishing partial artifacts.
- No client-controlled cap, new secrets, paid calls or changes to historical tasks.

## Ledger

- Ruling: continue in the existing dirty workspace rather than create a branch/worktree, because this is an incremental change to the user's ongoing integration and running environment. No unrelated edits or Git operations.
- Ruling: a dedicated frozen run_config field, not a new prompt version or mutable global, distinguishes new and old review-v2 tasks without changing their output protocol.
- TDD: the initial 14 focused checks exposed 22 assertion/subtest failures for the missing frozen cap and fixed 2048 worker limit before implementation; all 14 passed after the minimal fix. Four additional compatibility, actual-usage and HTTP integration checks brought the focused suite to 18 passing tests.
- Verification: 190 offline backend tests across 12 suites passed, including all 18 new checks. Parsed 31 Python files with ast.parse successfully; git diff --check passed. Expected invalid-result fixture warnings are intentional rejection-path coverage, not live provider failures.
- Scoped local review: new real review submissions alone freeze 4096; existing idempotency replay exits before configuration creation. Loader validation rejects invalid cap types/values, missing caps remain 2048, and the worker still bounds output by remaining estimated budget. No blocking issue found in this change; this was a local review, not an independent agent review.
- Handoff: in backend, stop the API with Ctrl+C and run `uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`. In the original authenticated Runner terminal, stop with Ctrl+C and run `uv run --locked python -m app.runner_worker`; do not close that terminal because its working API key was set only in its environment. Restart both before submitting a new task. No migration or frontend restart is needed.
- Manual acceptance remains pending: recreate the review with the same two ready papers and question, steps 10, total tokens 16000 and timeout 180 seconds. This may incur model charges; 4096 does not guarantee complete JSON. Historical tasks remain unchanged. Record the new task ID, terminal status and citation/table checks after the user submits it.
- Boundaries: no real network/model requests, database changes, service restarts, commits or pushes were performed for this change. Existing unrelated dirty work was preserved.

## Subsequent manual acceptance — 2026-11-13

- The user reported task `3cd9c072-c9f5-4b03-9d91-af2abd358570` executed successfully after the restart/new-submission handoff, then confirmed all four acceptance items: real-run information, review and comparison table, both papers' citations and physical PDF pages, and refresh recovery.
- The pending live gate above is closed for this one user-observed two-paper run only. The agent did not independently inspect this task's frozen configuration, usage or full artifact, did not submit another paid request, and does not infer actual output exceeded 2048 or that 4096 prevents all truncation.
- Detailed evidence boundaries and closeout checks are recorded in `docs/superpowers/plans/2026-11-13-real-review-acceptance.md`. The user subsequently authorized documentation closeout and a local Git commit; earlier no-commit ledger entries describe their original execution stage, not the current handoff.
