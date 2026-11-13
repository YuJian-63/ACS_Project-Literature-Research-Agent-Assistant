# Paragraph-bound citations for single-paper results

This records the v3 design. New-task defaults were subsequently advanced to v4 after a live quote mismatch; see `2026-11-13-evidence-selection.md`. Existing v3 tasks retain this contract and parser.

## Evidence and scope

The user reported a second QA failure. Read-only API inspection confirmed task `17d42ef2-00c8-4885-b8e3-74e025d85f7e` used `evidence-v2` and failed with `unused_citation` and provider finish reason `stop`. The prompt update was active but insufficient. Invalid raw responses were not retained, so the exact omitted markers and citations cannot be reconstructed.

The existing single-paper protocol asks the model to maintain two representations: inline positional markers and a separate citation array. The validator correctly rejects disagreements. Further prompt wording cannot enforce this relationship. Changing to paragraph-bound evidence removes that coordination requirement; increasing retries would instead add model calls, and relaxing the old validator would alter existing task semantics.

## Design

- New real summary/QA tasks use frozen prompt version `evidence-v3`. Model output is `{"paragraphs": [{"content_markdown": "...", "citations": [{"chunk_id": "...", "quote": "..."}]}]}`. Each paragraph contains only its supporting citations; the model generates no citation numbers or markers.
- The server assigns citation numbers in first-use order and appends their markers to each paragraph. Identical evidence reused across paragraphs shares one citation; duplicate evidence within a paragraph is rejected. No supplied paragraph or citation is silently discarded.
- Pass the rendered result through the existing strict validator for chunk identity, exact contiguous quotes, duplicate final citations, referenced indices and final output size. Paper identities and physical page numbers remain server-derived.
- A paragraph may have an empty citation list to express insufficient evidence, as with the existing result contract. This does not prove semantic support; live manual review remains necessary.
- Legacy `evidence-v1`/`evidence-v2` tasks keep their original prompts and parser. Review remains `evidence-review-v1`, including table-only citations. External API/artifact structure, database schema, budgets and model-call count do not change.
- The empty-evidence path emits the schema matching the frozen version without a model call. Malformed paragraph output, embedded citation markers, invalid source identities or fabricated quotes fail; no legacy fallback or automatic retry is added.

## Implementation and acceptance

1. Add failing local regression tests for paragraph rendering, evidence rejection, version freezing and Runner dispatch.
2. Implement the versioned prompt/parser/Runner path and preserve legacy/review behavior.
3. Run the combined local suite, syntax/whitespace checks and a separate review of changed code.
4. Restart API and Runner for one user-guided QA acceptance, verifying `evidence-v3`, persisted citation metadata, quote/semantic support and refresh recovery. Local fixtures cannot establish real generation success. Do not submit paid tasks or commit changes automatically.

## Implementation evidence

Implemented the versioned path and observed 20 new local checks fail before implementation, then pass. The combined 72-check suite passed, including legacy single-paper and multi-paper review regressions. Author self-review found no blocking issue in version dispatch, rendering or external artifact compatibility. Actual v3 generation and manual semantic acceptance remain pending; the backend does not claim that structural source validation proves a conclusion is supported by its quote.
