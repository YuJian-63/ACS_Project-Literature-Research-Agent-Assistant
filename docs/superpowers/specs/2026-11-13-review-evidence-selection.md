# Review evidence selection v2

## Approved scope

The user approved upgrading real multi-paper review before live acceptance on 2026-11-13. New review tasks freeze `evidence-review-v2`. Existing `evidence-review-v1` tasks, including jobs without a stored prompt version, keep their original prompt and strict parser. Summary/QA v4, database schema, public artifacts and frontend stay unchanged.

## Contract

Reuse the deterministic, exact, at-most-1000-character passage registry from single-paper v4. The review prompt includes `selected_papers` once and an evidence list with `evidence_id`, `paper_id`, physical `page_number` and `quote`. Evidence IDs are unique within the whole task, not reset per paper. Source ownership is derived from stored chunks, never from model output.

The model returns only:

```json
{
  "paragraphs": [{"content_markdown": "Supported finding.", "evidence_ids": ["E1"]}],
  "comparison_table": {
    "columns": [{"key": "method", "label": "Method"}],
    "rows": [{"paper_id": "selected paper UUID", "cells": {
      "method": {"value": "Reported method", "evidence_ids": ["E1"]}
    }}]
  }
}
```

The example row is repeated for every selected paper, in frozen selection order. Paragraphs may cite multiple selected papers. Non-null research cells must cite evidence belonging to that row's paper; unreported information uses `value: null` and an empty ID list. Evidence may be shared across paragraphs and cells, but may not repeat within one paragraph/cell.

The server resolves IDs and assigns one citation pool in first-use order: paragraphs first, then rows in selection order and cells in declared column order. It renders paragraph markers and table citation references, then invokes the existing strict review validator. Table-only citations are valid. Final artifacts remain `content_markdown`, `citations`, `comparison_table`; source quotes, chunk identities, pages and C numbers are server-owned.

Reject unknown IDs, duplicate selections, model-generated citation markers in text, extra quote/identity/index fields, cross-paper table citations, malformed columns/rows/cells, invalid text and existing quote/count/size violations. Do not repair output, normalize quotes, drop citations or retry the model. All-empty review evidence continues using the existing zero-call insufficient-evidence result. No dependency, migration, automatic task submission or Git commit is included.

## Acceptance boundaries

Offline tests establish deterministic protocol behavior, not model generation reliability or semantic support. Live acceptance requires a new two-paper review after restarting API and Runner, plus human inspection of conclusions, table source ownership, physical PDF pages and refresh recovery. Existing QA acceptance does not establish review acceptance.

## Implementation verification — 2026-11-13

- Added 32 offline checks covering the v2 protocol, table-only/shared citations, ordering, source ownership, tampering, limits, frozen versions, budgeting and Runner success/failure/no-call paths. Observed missing-behavior failures before implementation and a separate v1-to-v2 version-freeze failure after correcting the test's dummy settings fixture.
- All 128 checks across eight regression suites passed. Syntax checks passed for 30 backend Python files and the new runtime script; whitespace checks passed. Runtime checks remain ignored under the existing project convention; formal tracked tests/CI remain a separate backlog item.
- Independent scoped review found no blocking issue. No frontend, database schema, dependency, transaction/lease or generation-cap change was required.
- No live model request, task submission, service restart, commit or push was performed. Two-paper real review acceptance remains pending.

## Subsequent live acceptance — 2026-11-13

After the separate output-cap adjustment, the user reported successful task `3cd9c072-c9f5-4b03-9d91-af2abd358570` and confirmed all manual review/table, citation/page and refresh checks. This supersedes the earlier pending status for one user-observed two-paper run only; the agent did not independently inspect the successful task's frozen settings, actual usage or full result. See `../plans/2026-11-13-real-review-acceptance.md` for provenance and limits.
