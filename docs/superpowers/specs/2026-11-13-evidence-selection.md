# Server-owned citation excerpts

## Observed failure

Task `2ef06d5b-9ed9-43b6-8179-1d89512cba2b` used `evidence-v3` and failed with `quote_mismatch`, finish reason `stop`. This is a different integrity check from the earlier unused-citation failures. The invalid raw response was not saved, so its precise wording and the distinction between rewriting, formatting changes and a wrong chunk cannot be recovered. A read-only job load found 16 selected chunks, 22268 source characters, maximum chunk length 2000 and estimated v3 input usage 9970 tokens; no model request was made.

## Correction within the existing acceptance scope

Keep paragraph-bound citations, but remove the remaining requirement for the model to reproduce source text. New summary/QA tasks freeze `evidence-v4`. The server divides the selected stored chunks into contiguous passages of at most 1000 characters, preferring a whitespace boundary in the latter half of each passage. Passages never cross a chunk or physical page. No internal whitespace, Unicode, punctuation or hyphenation is normalized. Blank-only passages are omitted.

The prompt supplies task-local evidence IDs, physical pages and exact passage text, plus single-paper metadata once. The model returns `{"paragraphs": [{"content_markdown": "...", "evidence_ids": ["E1"]}]}`. It chooses evidence rather than writing a quote or UUID. The parser reconstructs the same deterministic passage registry from the job's evidence, resolves every ID, and then uses the existing paragraph renderer and strict result validator. Final quotes must still be exact substrings of stored chunks; identities and pages remain server-owned. Unknown IDs, duplicate IDs within a paragraph, embedded markers and additional model-supplied quote/identity fields fail. Empty evidence lists remain available for insufficient-evidence paragraphs.

This is a new versioned output contract, not fuzzy quote matching or a fallback for old responses. Existing v1/v2/v3 tasks retain their original parsers and strict rejection rules; review stays at `evidence-review-v1`. Public artifacts, database schema, transaction/lease behavior, budgets and the one-call workflow stay unchanged. Structural validity does not establish that a selected passage supports a conclusion; manual semantic acceptance remains required.

## Verification plan

1. Observe failing regression tests for deterministic bounded passage construction, exact-text resolution, schema rejection, frozen versions, budgeting and Runner dispatch.
2. Implement the v4 path and run new plus existing regressions; verify the real failed job's v4 input estimate locally without calling the model.
3. Review the version boundary and unchanged persistence path, update setup/API/acceptance records, and run syntax/whitespace checks.
4. Guide API/Runner restart and one new QA acceptance. Do not automatically submit tasks, retry paid calls, mutate old tasks or commit changes.

## Implementation evidence

- Observed 24 new local checks fail on the missing registry/parser/version behavior before implementation; all 24 then passed. The combined suite passed 96 checks, including legacy/review regressions. Historical v3 tests explicitly select v3 instead of assuming it remains the new-task default.
- A read-only replay of the actual failed job's selected evidence produced 32 passages, each at most 1000 characters. Resolving all 32 through the new parser passed the existing exact-substring validator. This used a local fixture answer and did not submit a task or publish an artifact.
- Estimated v4 input usage for that job is 9202 tokens, leaving the existing 2048-token generation cap within the original 16000-token task budget. This is a local estimate, not provider-reported usage.
- Author self-review checked deterministic registry reuse, no normalization of stored text, unknown-ID rejection, legacy parser dispatch and unchanged artifact persistence. No blocking issue was identified. Live v4 generation and semantic/manual acceptance remain pending; no actual model request or Git commit was performed.

## Live QA acceptance — 2026-11-13

- Task `27da56a0-a3aa-4f0b-b1d7-9aa04cde0231` succeeded as real `evidence-v4` QA, with one model call and seven citations. Independent read-only checks confirmed persisted markers, selected-paper ownership, exact stored-source quotes, physical-page consistency and passage-registry membership.
- The user subsequently confirmed all manual checks normal: answer coverage, unreported-information handling, PDF navigation and physical pages, semantic support from each citation, and refresh recovery. This one QA acceptance is complete; model accuracy across tasks, v4 summaries and real multi-paper review are not established by it. The chronological evidence record is in `../plans/2026-11-13-model-thinking-mode.md`.
