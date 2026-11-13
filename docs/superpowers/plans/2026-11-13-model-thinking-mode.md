# Model Thinking Mode Implementation Plan

> Execute inline with superpowers:executing-plans. Commit only when requested; no live model requests during implementation.

**Goal:** Add optional task-frozen thinking mode and prepare the user's first DeepSeek summary acceptance.

**Architecture:** Settings -> real task run_config -> ResearchJob -> Chat Completions payload; preserve existing provider-default requests.

**Spec:** `docs/superpowers/specs/2026-11-13-model-thinking-mode-design.md`.

## Task 1: Configuration and model request

- [x] Add ignored `runtime/verify-model-thinking.py` checks for default omission, enabled/disabled payloads, invalid modes, task freezing and old-job compatibility; observe expected RED.
- [x] Update `backend/src/app/config.py`, `model_client.py`, `tasks.py` and `runner_worker.py` without migration or dependency changes. Use the existing JSONB snapshot, never store API keys.
- [x] Run the new checks GREEN and existing MVP-1B/MVP-2 unit regressions with inherited model configuration removed from the test process.
- [x] Update `.env.example`, backend setup and API contract; verify whitespace and ignored configuration/runtime assets.

## Task 2: User-guided live acceptance

- [x] Guide adding `LLM_THINKING_MODE=disabled` to local ignored configuration, clearing only current-terminal overrides, and checking effective non-secret settings.
- [x] Guide API restart and independent real Runner startup with matching database/storage/configuration; create one ready-paper summary and inspect non-Mock result, evidence and refresh recovery.
- [x] Record actual live result or failure without equating mocked tests with provider acceptance.

## Execution record

- The user confirmed the corrected DeepSeek endpoint/model and real Runner configuration. Implementation continues under the existing request to proceed with real-model acceptance; provider choice and credentials are not reopened.
- New verification: eight checks first failed on the expected missing Settings/client/job/config-snapshot support, then all eight passed after implementation. Mock HTTP verifies exact provider-neutral/explicit thinking payloads while preserving JSON response format and output limits; local session fixtures verify task snapshot and Worker propagation, not real database transactions.
- Regression verification: existing MVP-1B 14 and MVP-2 15 checks passed (29 total), with inherited application settings removed only inside the test process. An initial unittest discovery attempt found zero tests because these historical filenames contain hyphens; explicit module loading with an asserted count of 29 was used for the actual regression result.
- Default provider payload and old-task behavior remain unchanged. No real upstream model request, database change, dependency change or local secret-file edit was performed. User configuration and live task acceptance remain pending; changes remain uncommitted.

## First live failure and diagnostic follow-up

- User confirmed langgraph/official DeepSeek endpoint/deepseek-flash/disabled thinking configuration, API restart with healthy/ready results, and real Runner launch. The first live summary failed with INVALID_AGENT_RESULT; successful model-result acceptance remains pending.
- Read-only local API inspection identified task `a705e435-2764-4236-aa4e-492d02e31b21`, is_mock=false, model_id=deepseek-flash, workflow/prompt=langgraph-v1/evidence-v1, budget=10 steps/16000 tokens/180 seconds. The task had empty error.details. No additional model request or task submission was made by the agent.
- Ruling: do not infer quote mismatch, invalid JSON or truncation from the generic failure. Existing code discarded raw invalid output and provider finish_reason. Add safe diagnostic categories before requesting one controlled user-run reproduction; never weaken exact-substring/identity/citation validation, alter the failed record or retry automatically.
- Added ignored `runtime/verify-result-diagnostics.py`: seven checks observed expected missing-feature RED, then GREEN. Coverage includes JSON/schema/quote/identity/marker classifications, provider finish-reason allowlisting, graph propagation and legacy completion compatibility, Runner failure/no artifact, and current-owner-only detail persistence. No prompts, provider body or source quotes are included in public diagnostics or logs.
- New diagnostic checks (7), thinking checks (8), and existing MVP-1B/MVP-2 checks (29) all passed, 44 total, with local fake HTTP/session fixtures only. Native transactional regression was not rerun for this diagnostic-only change. User must restart the real Runner before one controlled new task; earlier failed output cannot be recovered. This is observability work, not a claimed fix of the unknown live generation failure.

## Subsequent live summary execution

- User reported task `e12f73c7-6f45-45da-a784-75807081101d` completed. The agent then independently read that task and its artifacts through the local API without submitting a task or calling the model.
- API confirmed status=succeeded, is_mock=false, model_id=deepseek-flash; one non-Mock artifact with 572 body characters and five citations. Recorded usage: input_tokens=7650, output_tokens=759, total_tokens=8409, model_calls=1, tool_calls=0; execution_ms=5462.
- Citation keys C1 through C5 point to physical pages 1, 2, 3, 6 and 7 respectively. Local API checks confirmed all refer to the selected Paper, all page numbers are within its nine pages, and every citation marker is present in the artifact body. This checks persisted identities, bounds and marker presence, not semantic support for each conclusion.
- Manual PDF/quote comparison, semantic support, non-Mock UI presentation and successful-result refresh recovery are the next user acceptance gate. No second success or generation-quality claim is made yet. The original failed task's cause remains unknown; a subsequent successful generation does not establish that diagnostic instrumentation fixed model output.

## Manual summary acceptance completed — 2026-11-13

- In response to the four-item acceptance checklist, the user confirmed all normal: non-Mock labeling/body display, all five quotes and physical pages, support of the corresponding conclusions, and browser refresh recovery for task `e12f73c7-6f45-45da-a784-75807081101d`.
- Evidence distinction: the agent previously verified task/artifact/citation metadata via read-only local API calls; PDF text/semantic support and browser behavior were checked by the user, not independently observed by the agent.
- This plan's optional thinking-mode implementation and one real DeepSeek summary acceptance are complete. It does not establish general model accuracy or reproducibility; the earlier failed generation remains unexplained. Real QA, multi-paper review and the broader MVP-2.1 formal tests/CI work are not complete.
- Next user-guided acceptance: one single-paper QA using the same ready Paper, with bounded inputs/budget and manual citation/refresh checks. No further task or paid model request was submitted by this documentation update. All current code/documentation changes remain uncommitted pending a user request.

## Live QA failure and versioned citation prompt correction — 2026-11-13

- Read-only local API inspection confirmed QA task `bdb8e3a7-c5f5-4df6-8b2f-71d98f1f99aa` failed with `INVALID_AGENT_RESULT`, validation_reason=`unused_citation`, model_finish_reason=`stop`, is_mock=false and prompt_version=`evidence-v1`. This identifies an unused citation rather than provider length truncation; the discarded model response cannot be inspected to recover its exact citation layout.
- Code inspection found the single-paper prompt explained citation markers but omitted the validator's requirement that every citation be used. Added `evidence-v2` for new real summary/QA tasks, explicitly requiring citation usage, valid indices and a final index check. Existing v1 tasks retain their original prompt and review retains `evidence-review-v1`, including table-only citations.
- Persist the version at task submission, load it into ResearchJob, and use the same version for prompt construction and input-token estimation. No schema migration or dependency change is required. Citation validation remains strict; no silent citation pruning, automatic repair, retries or changes to failed records were added.
- Eight ignored `runtime/verify-citation-prompt.py` checks observed expected RED before implementation, then passed. Coverage includes new single-paper rules, legacy/review behavior, invalid-version rejection, graph/job version propagation and unchanged strict validation. Fresh combined regression verification passed 52 checks: MVP-1B 14, MVP-2 15, thinking mode 8, diagnostics 7 and citation prompt 8. Backend syntax checks and whitespace validation also passed. Fixtures do not substitute for native PostgreSQL or live generation acceptance.
- Pending user action: restart both API and real Runner, create one new QA task with the same question and budget, confirm `versions.prompt_version=evidence-v2`, then check citations and refresh recovery. No additional model request was made during diagnosis or implementation. Real QA acceptance remains pending, and changes remain uncommitted.

## Repeated v2 QA failure and paragraph-bound citations — 2026-11-13

- The user reported task `17d42ef2-00c8-4885-b8e3-74e025d85f7e` failed. Read-only API inspection independently confirmed QA, is_mock=false, prompt_version=`evidence-v2`, `unused_citation` and finish_reason=`stop`, with the original question, Paper and 10-step/16000-token/180-second budget. The previous prompt change was active but insufficient. The failed raw output was not retained; its exact marker arrangement remains unknown.
- Design: `../specs/2026-11-13-paragraph-citations.md`. New real summary/QA tasks freeze `evidence-v3`, returning paragraph-bound evidence; the backend creates citation indices, reuses identical evidence across paragraphs and runs the rendered result through the existing strict validator. No paragraph or evidence is silently removed. Legacy v1/v2 prompts and parsers, review table-only citations, API artifact shape, native transaction/ownership logic, budgets and model-call count remain unchanged.
- Added 20 ignored `runtime/verify-paragraph-citations.py` checks and observed expected missing-parser/version RED. After implementation all 20 passed, including deterministic rendering, shared citations, duplicate/unknown/fabricated evidence rejection, schema and byte/count limits, no-evidence handling, frozen versions, exact prompt estimation and Runner success/failure without automatic retry. Existing v2 prompt checks now explicitly select v2 rather than assuming it is the latest default.
- Fresh combined regression suite passed 72 checks: prior 52 plus new 20. Tests use local model/session fixtures, not live generation or native PostgreSQL transactions. A separate author review using the code-reviewer workflow checked parser dispatch, unchanged legacy/review prompts and compatibility with the existing artifact persistence/frontend path; no blocking finding was identified. This is self-review, not independent reviewer approval.
- User-guided live gate remains pending: restart API and real Runner, create one new QA task with unchanged input/budget, confirm `evidence-v3`, then verify persisted citation metadata, quote/page/semantic support and refresh recovery. Do not count the failed v2 task as v3 acceptance. No additional model request, database mutation or Git commit was performed during this correction.

## Live v3 quote failure and server-owned excerpts — 2026-11-13

- Read-only API inspection confirmed task `2ef06d5b-9ed9-43b6-8179-1d89512cba2b` was a real QA using `evidence-v3`, failed with `quote_mismatch`, and finished normally with `stop`. This identifies a different rejected invariant; it does not establish whether the model rewrote text, changed formatting or associated a quote with the wrong chunk, because the failed response was discarded.
- Design: `../specs/2026-11-13-evidence-selection.md`. New real summary/QA tasks freeze `evidence-v4`: a deterministic registry supplies task-local IDs and exact stored passages up to 1000 characters; the model chooses IDs per paragraph, and the backend resolves original quotes/identities/pages before invoking the paragraph renderer and strict validator. No fuzzy matching, legacy response fallback or automatic retry is added. Existing v1/v2/v3 and review behavior remains frozen.
- Added 24 ignored `runtime/verify-evidence-selection.py` checks; observed expected missing-feature RED, then GREEN. Coverage includes source preservation/bounds/page boundaries, Unicode/whitespace handling, stable IDs, unknown/duplicate ID and field-override rejection, legacy compatibility, no-evidence schema, input estimation, frozen version propagation and one-call Runner success/failure. Combined regression verification passed 96 checks: prior 72 plus new 24.
- Read-only loading of the actual failed job found 16 selected chunks and 22268 source characters. A local fixture selecting all 32 derived passages passed the unchanged exact-substring validator, with maximum quote length 1000. Estimated v4 input usage was 9202 tokens; the existing 2048-token output cap fits the original 16000-token budget. No fixture answer was stored or published, and no provider call was made.
- Separate author self-review checked registry/prompt/parser consistency, original-text preservation, strict ID resolution and unchanged external artifact/persistence behavior; no blocking finding was identified. This does not substitute for independent review, native transactional acceptance or model-generated semantic validation.
- Pending user-guided live gate: restart API and real Runner, create one new QA with the same Paper/question/budget, verify `evidence-v4`, then check actual citations, physical pages, semantic support and refresh recovery. The earlier failed record remains unchanged. No model request, business/schema write, dependency change or Git commit was performed during this correction.

## First successful v4 QA execution — 2026-11-13

- Before execution, read-only API inspection confirmed task `27da56a0-a3aa-4f0b-b1d7-9aa04cde0231` was queued, real QA, `deepseek-flash`, `evidence-v4`, with the original Paper and 10-step/16000-token/180-second budget. The user then started the real Runner and reported success.
- Subsequent independent API inspection confirmed succeeded, is_mock=false, no error and one persisted non-Mock artifact with 855 body characters and seven citations. Actual recorded usage was input_tokens=6733, output_tokens=528, total_tokens=7261, model_calls=1 and tool_calls=0; execution_ms=4339. Earlier input estimates were local estimates, not these provider-reported counts.
- Citation keys C1 through C7 refer to physical pages 2, 3, 3, 4, 2, 2 and 7. Read-only API/source checks confirmed every key is used in the body, every body marker resolves, every cited Paper belongs to the task, all seven quotes are exact stored-source substrings, all pages match the stored chunks, and all quotes belong to the v4 passage registry. No new model request, task submission or business write was performed during these checks.
- Execution and structural/source integrity passed for this one task. Manual acceptance remains pending: answer coverage of data/methods/limitations, semantic support of each conclusion by its evidence, PDF navigation/display and browser refresh recovery. Do not equate a successful run or exact source matches with proven semantic correctness or general generation reliability. Changes remain uncommitted.

## Manual v4 QA acceptance completed — 2026-11-13

- In response to the final three-item checklist for task `27da56a0-a3aa-4f0b-b1d7-9aa04cde0231`, the user confirmed all normal: the answer covers data, methods and limitations with unreported information identified; all seven citations open the correct PDF physical pages and support their associated conclusions; browser refresh restores task status, body and citations.
- Evidence boundary: execution/version/usage and exact stored-source identities/quotes/pages were previously checked independently through read-only API and source reads. PDF navigation, answer coverage, semantic support and browser recovery were checked by the user, not independently observed through browser automation.
- This single real DeepSeek QA acceptance is complete. The earlier real single-paper summary also has its own accepted record; neither proves v4 summary acceptance, general generation reliability, real multi-paper review quality or completion of the broader MVP-2.1 tests/CI work. Real multi-paper review remains the next acceptance scope; it still uses its separate `evidence-review-v1` protocol.
- Updated documentation only. No additional model request, task submission, business-data modification or Git commit was made. Current implementation/documentation changes remain uncommitted pending an explicit request.
