# arXiv import metadata reliability

Diagnosis: recent local imports included five ARXIV_TIMEOUT failures and three FILE_TOO_LARGE failures. Exact-version metadata for a failed sample and its complete 882991-byte PDF succeeded via the actual worker interpreter; another exact-version metadata request was rate limited before PDF download. A control metadata URL timed out at 15 seconds. This demonstrates upstream variability and a redundant pre-download request, not universal PDF availability.

Approach: reuse only server-verified search metadata for the exact requested version. Persist it on the import record so separate/restarted workers can read it. Cache lookup expires with search results; unavailable snapshots use existing metadata fetch. Retry may attach currently cached metadata to an old failed record. Preserve all URL, TLS, PDF-size, lease, deadline, shared gate and no-auto-retry safeguards.

- [x] Add tests for trusted cache lookup, persistent metadata reuse, retry snapshot hydration and legacy fallback.
- [x] Add nullable JSONB metadata snapshot migration, ORM/reference schema, cache lookup, submit/retry wiring and worker reuse.
- [x] Add safe stage/phase/elapsed logging for import failures.
- [x] Run isolated PostgreSQL suite and relevant offline tests; apply additive local migration and validate real source path without changing user imports.

## Verification and operational result

- 28 isolated PostgreSQL ownership/import tests passed, including metadata persistence, retry hydration, skipped duplicate metadata call, legacy metadata fallback, schema reference parity and migrations.
- Five search/cache tests passed, including exact-version lookup, TTL and defensive copying.
- Independent review found no important correctness/security issues.
- Real-source test used actual worker code, a temporary isolated PostgreSQL database and the validated snapshot for 2202.09741v5. Complete PDF download and paper/source commit succeeded: 882991 bytes, 3.32 seconds (including source cooldown). Test database and files were removed; real user records were not retried or modified.
- Local additive migration applied: 20261118_0006. API /health and /ready returned 200. The idle old Import Worker was gracefully stopped and replaced by a worker running the updated code.
- Initial live-test fixture omitted the source gate seed after TRUNCATE; the fixture was corrected before the successful live run. This was isolated test setup, not a change to production gate behavior.

Boundary: arXiv may still independently time out or rate limit requests; removing the redundant metadata query does not guarantee every PDF is available. Three recent failures were FILE_TOO_LARGE, and the 20 MiB limit remains. Existing failed records do not automatically retry: search again to seed verified metadata, then explicitly retry.
