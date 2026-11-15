# Cross-language evidence implementation plan

> Execute inline with superpowers:executing-plans. No commits or external model requests are part of implementation.

**Goal:** Answer Chinese questions about English papers using bounded multilingual retrieval, structural coverage and one evidence supplementation round.

**Architecture:** Snapshot selected paper text and parser provenance at submission. Perform query expansion and evidence selection in the leased Worker; checkpoint query plans, evidence, usage and per-paper analyses in the existing JSON state. Keep legacy workflows readable.

**Tech Stack:** Python, SQLAlchemy/PostgreSQL, existing compatible chat client, React/TypeScript.

**Spec:** Approved solution in the conversation dated 2026-11-15.

## Constraints

- Selected, owned papers only; no network search or new vector service.
- At most three expanded queries, 512 output tokens and 15 seconds for expansion.
- One supplementary selection per answer or paper; every model call is reserved and settled.
- Preserve exact original substrings and citation validation. Snapshot parser version and full source chunks with an explicit size bound.
- No HTTP-time model calls; legacy plans remain supported. Migration 0005 extends the lifecycle check for resumable search tasks.

## Review focus

- Zero lexical overlap must not imply that the paper contains no answer.
- Service degradation and no parsed text must be distinguishable from insufficient selected evidence.
- Recovery must reuse frozen sources and completed retrieval checkpoints.
- Stale owners cannot change evidence, spend budget or publish results.
- Supplementing one paper must preserve other papers and stable evidence IDs.

## Tasks

- [x] Add failing offline tests for cross-language queries, structure, specific facts and unknown questions. Implement pure document ranking, query validation and bounded exact-text excerpts.
- [x] Add bounded source snapshots and automatic planning for expansion, generation, supplementation and recovery. Preserve legacy policy entry points.
- [x] Add Worker checkpoints and model usage reservations for retrieval and single tasks; integrate per-paper supplementation with staged review.
- [x] Add accurate diagnostics and bilingual event/result text; document operation and compatibility.
- [x] Run targeted and full offline backend tests, frontend checks/build, and available isolated PostgreSQL acceptance tests.

## Decisions and verification

- Use the existing task JSON state for source and retrieval snapshots, bounded to 8 MiB by default; no new index or database table.
- Do not translate paper text: citations always refer to the immutable original text.
- Ruling: add migration 0005 for the lifecycle constraint. Existing SQL permits requeued started tasks only for review-v2, so JSON snapshots alone cannot support safe recovery. No data reset is needed.

## Verification evidence

- Offline backend discovery: 157 tests, 96 passed and 61 environment-gated skips.
- Native ownership/search PostgreSQL suite: 21 passed in a fresh randomly named database, including Chinese QA, usage totals, frozen sources, recovery deadlines, stale owner fencing and schema parity.
- Native staged review PostgreSQL suite: 8 passed in a freshly created review_tests database. Only that temporary database was removed afterward.
- Offline six-paper review: all six papers supplemented with unknown model usage, bounded reservations and checkpoint replay without duplicate calls.
- Frontend verify:review and production build passed; existing bundle-size warning remains.
- Offline Playwright browser checks passed for Chinese/English partial-evidence alerts and comparison labels; the test server was stopped.
- No real model, arXiv or SMTP calls. The actual configured application database was not upgraded. Apply migration 0005 and restart services before manual acceptance.
- Review: confirmed legacy plan loading, per-user source scope, conservative unknown usage, append-only evidence IDs and exact source-substring validation. Answered single-task paragraphs must include evidence IDs.
