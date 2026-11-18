# Library deletion and import status implementation plan

**Goal:** Delete unused papers with confirmation, synchronize arXiv result state, and expose manual retry for failed downloads.

**Architecture:** Add an authenticated DELETE endpoint. Lock the paper before checking TaskPaper references; reject referenced or actively parsing papers. Delete source/import mapping, chunks and paper transactionally, then clean up its controlled file. Existing task references are never removed. Search status always comes from current server state, separate from cached arXiv metadata.

**Approved requirement:** Papers referenced by any task cannot be deleted. This was explicitly selected by the user.

**Implementation decisions:** Per-row confirmation; remove deleted paper from selection and close its reader. Preserve filters and correct pagination after deleting the final row. Manual retries remain constrained by authentication, expected attempt and import capacity. Permit explicit retry of any failed download; historical retryable classification does not hide the action. No automatic retry of failed downloads.

**Alternatives:** Soft deletion would preserve historical original files but was not selected. Unrestricted cascading deletion would damage historical citations and is excluded.

- [x] Backend: tests for unused deletion, referenced/foreign-user/processing rejection and reimport; implement endpoint with existing ownership and CSRF protection.
- [x] Frontend: per-row deletion confirmation, errors, selection/reader cleanup; synchronize search status and retry fallback.
- [x] Verify: isolated backend checks, build and browser tests with mocked download outcomes, deletion and reimport.

## Verification

- Isolated native PostgreSQL ownership suite: 26 tests passed, including unused/reference/foreign-user/processing/CSRF deletion and delete/reimport with manual retry.
- `npm run build` and `npm run verify:review`: passed.
- Mocked Chrome browser: deletion cancel/confirm, reference rejection, selection cleanup, deleted search status, focus synchronization, missing import detail retry fallback, initial status-error polling recovery, delayed deletion preserving newer reader/selection, and mobile reader deletion passed.
- Notification browser regression: visible close/padding at 1440/390/320px, import success/failure, maximum three notices and five-second dismissal passed.
- Review findings addressed: do not overwrite live URL state with the pre-delete snapshot; retry hydration while a pending snapshot has no known import detail.

Ruling: All failed downloads may be manually retried. Previously non-retryable source failures can recur; source validation, quotas and expected-attempt concurrency checks still apply. Successful imports with parsing failures cannot be overwritten by download retry.
Ruling: Work continues in the existing workspace to preserve the user's ongoing uncommitted UI changes. No branch or commits created.
