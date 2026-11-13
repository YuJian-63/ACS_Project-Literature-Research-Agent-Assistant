# arXiv metadata read timeout

## Approved change

On 2026-11-13 the user approved increasing only metadata read waits, after a search failed with `ARXIV_TIMEOUT`. Local health/readiness and direct DNS/TCP/TLS checks succeeded. The application reproduced a 504 after 5.62 seconds; one diagnostic request with a 15-second read timeout returned HTTP 200 after 12.41 seconds. A later one-result application search succeeded in 0.59 seconds. These observations establish this slow-response failure mode, not general upstream availability.

## Design

- In `perform_request`, metadata requests (search and exact-version metadata; no PDF destination) use a read timeout of `min(15, remaining_seconds)`.
- Connect, write and pool waits remain `min(5, remaining_seconds)`. PDF reads also remain `min(5, remaining_seconds)`.
- Keep the existing 20-second metadata deadline, parent termination and child watchdog; the read wait is not a replacement or extension of that total deadline. Shorter remaining deadlines always win.
- Preserve fixed URLs, TLS verification, ignored environment proxies, redirect/size restrictions, shared permit/cooldown, Retry-After handling and no automatic retry.
- No database, dependency, frontend, configuration-key or model-runner change. No model calls, task creation or Git commit.

## Verification

Use offline HTTP fixtures to model a response requiring 12.4 seconds of read allowance, inspect all four HTTPX timeout phases for search/exact/PDF and short remaining budgets, and verify timeout errors make only one request. Existing arXiv tests must continue proving watchdog/deadline, subprocess isolation, byte limits, URL safety and retry behavior. Document fresh results separately from manual post-restart search acceptance.

## Implementation and live boundary

All six new checks, 28 existing arXiv checks and 128 earlier research checks passed: 162 combined offline tests. Syntax and whitespace checks also passed. No dependency, schema, frontend or configuration change was required. Checks remain in ignored runtime scripts, not a formal tracked test/CI suite.

Independent scoped review found no blocking issue and separately reran the six new timeout checks. It did not rerun the combined suite or send live requests.

One subsequent real application query with limit=10 still timed out after 15.63 seconds. The increased read allowance is implemented, but upstream responsiveness is not guaranteed and search recovery is not accepted. Do not extend limits or retry automatically; manual PDF upload can continue the separate two-paper review acceptance. No import/research task was submitted, model invoked or Git commit/push made.
