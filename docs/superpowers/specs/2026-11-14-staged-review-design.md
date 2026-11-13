# Automatic budgets and staged literature reviews

Approved approach: automatic server budgeting with per-paper analysis, short synthesis sections, deterministic assembly and strict citations. The user approved this approach on 2026-11-14. Implement inline; no external model calls, commits, service restarts or changes to the user's database during development.

## Contract

New real review tasks use langgraph-review-v2 / evidence-review-v3. Summary, QA, mock execution and historical review versions preserve their runners. Reviews ignore caller budgets; the backend freezes a versioned bounded policy and per-paper evidence quota at submission. Review idempotency hashes exclude the ignored caller budget; replay also recognizes existing legacy hashes before policy planning. Existing response budget fields remain server-owned snapshots.

The server selects distributed source passages per paper, favoring abstract/introduction, methods/results and conclusion coverage without requiring English/Chinese lexical overlap. Each paper gets a bounded analysis call returning cells for common fixed comparison dimensions with original evidence IDs. Synthesis creates three short sections from validated analyses plus their source passages. The final table, identities, quotes and citation numbering are assembled by the server and passed through the existing strict review validator. A model never emits the entire multi-paper artifact.

Budget planning reserves one token per UTF-8 byte plus message overhead for byte-tokenized compatible providers, bounds accepted serialized analysis sizes, and uses, JSON overhead, stage outputs, a bounded retry reserve, server configured model context/output ceilings, 100 calls, 100000 task tokens and 1800 seconds. Evidence quotas shrink when necessary; impossible plans fail before model requests. Every call reserves input and output allowance durably before network I/O. Actual reported usage replaces reservations; missing/uncertain usage keeps conservative reservations and is labeled estimated. All attempts count, including invalid results and interrupted requests. Each unit allows at most two attempts; length retries request a more compact unit. No JSON repair or relaxed evidence checks.

## Persistence and recovery

Add tasks.review_state JSONB for evidence snapshots, plan execution, results and attempt reservations, separate from immutable run_config. Mutations lock the task and check owner, live lease and deadline. Only successfully validated units become checkpoints; successful usage settlement and result saving share one transaction. New staged reviews alone can be requeued on expired worker leases, preserving original started_at and all reservations/checkpoints; an in-flight attempt is uncertain and consumes its reservation. Expired task deadlines remain terminal. Old workers cannot reserve or commit a step after losing ownership. Final artifacts are published atomically only after complete validation.

## User experience

Hide budget inputs for review; submit only papers, question and workflow. Show translated per-paper and synthesis progress using structured event payloads. Show effective auto budget as read-only and distinguish estimated usage. Leave generated prose and source text unchanged on locale switching.

## Acceptance

Offline checks: 2/6/20 papers, long multilingual evidence/questions, bounded plans, per-paper coverage, two attempts at most, malformed JSON with stop, length truncation, unknown/duplicate/cross-paper evidence, missing usage, recovery, stale ownership, idempotency, legacy tasks and no partial artifacts. Native PostgreSQL integration uses an isolated database/schema only. Frontend typecheck/build and i18n checks. Live six-paper acceptance is a later user operation after migration and restarting API/Worker.

## Capacity qualification after verification

The 2—20 paper input range is not an unconditional capacity guarantee. Full twenty-paper evidence with conservative byte accounting can exceed the 100000 cumulative ceiling; reject before requests rather than sampling below 1000 characters per paper. Sparse twenty-paper fixtures fit. Each synthesis section sees its relevant analysis columns and their deduplicated original passages, and sections without supporting evidence are explicitly marked insufficient without a model call. Exact billing usage replaces reservations only when both input and output counts are reported.
