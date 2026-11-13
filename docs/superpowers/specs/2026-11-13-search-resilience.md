# Search resilience and safe diagnostics

## Approved scope

The user approved retaining successful search results, safe failure diagnostics, bounded manual retry and offline regression tests. This improves failure handling; it does not establish recovery of live arXiv search.

## Design

- Retain an in-memory frontend snapshot containing the successful page, its submitted keywords and its browser receipt timestamp. A failed or pending request must not relabel that snapshot as the new query. Successful empty pages replace previous results.
- Keep the latest attempted keywords and offset separately. Error retry repeats that exact request; pagination always belongs to the displayed snapshot. Existing sequence/cancellation fencing prevents obsolete responses from overwriting results or starting cooldowns.
- A failed import-status enrichment request is shown separately in the history area; it cannot turn a successful source query into a stale/failed search.
- Implementation choice: an `ARXIV_TIMEOUT` starts a five-second, search-only manual retry wait. Check the absolute deadline in the search handler as well as disabling buttons, including pagination. Preserve the shared 429/Retry-After cooldown for search and imports. No automatic search, retry or download is added; history refresh and import actions remain independent of search-only cooldown.
- Carry only an allowlisted failure phase through the isolated child protocol. Distinguish connection, request write, connection pool, response headers/body, total deadline, source gate, upstream status and response validation. Unknown failures remain `unknown`; do not infer a TLS-specific cause from a generic connection failure.
- Log search failures once at the API boundary using its generated request ID, phase, monotonic elapsed milliseconds and safe error code. Do not log keywords, URLs, contact emails, exception messages/tracebacks, raw responses, paper text or credentials. Diagnostic phase is internal and does not change the public error envelope.
- A supervised child exiting with its existing watchdog code 124 is classified as a total-deadline timeout rather than an invalid response. Other abnormal child exits retain the existing response-validation failure.
- Preserve metadata read <=15 seconds, other phases <=5 seconds, total metadata <=20 seconds, PDF budgets, source permits, subprocess isolation, successful-page cache and existing import history.

## Non-goals

No proxy/VPN changes, increased timeout, background retries, alternative provider, stale backend cache fallback, new dependency, database migration, service restart, Git commit/push, external arXiv request or paid model call.

## Acceptance

Offline tests cover phase mapping/protocol validation and safe correlated logs; browser tests cover old-result provenance, empty results, exact-page retry, query switching, cooldown bypass attempts, no automatic retry and unaffected import history. Existing arXiv and research suites plus the frontend build remain green. Live search recovery remains unverified.
