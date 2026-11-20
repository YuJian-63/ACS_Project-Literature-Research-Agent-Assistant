# Frontend and Backend Integration Fixes Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Resolve the six verified integration findings without changing the existing research workflow or page design.

**Architecture:** Preserve the four task states and use Agent outcome metadata for partial-result presentation. Keep raw Agent results intact while projecting comparison citations for the existing UI. Protect remote cancellation before deletion and preserve server-owned limits and question-driven answer language.

**Tech Stack:** React, TypeScript, FastAPI, SQLAlchemy, PostgreSQL, unittest, Playwright.

**Spec:** The integration audit and the user's approval to fix its findings; answer language follows the question, independently of interface language. An empty summary question retains Chinese as its documented default.

## Global Constraints

- Work on the current backend-dev-v2 branch; do not commit or push without a new user instruction.
- Preserve existing PDFs, user databases, historical results, structured comparison tables and citation return navigation.
- No new task status, budget control, language selector, dependency, model call or migration is required.
- Use isolated PostgreSQL fixtures; do not truncate or alter existing application databases.

## Review Focus

- A partial Agent result must remain readable and visibly distinguishable from full completion, including in research history.
- Comparison citations must use the same C1/C2 projection as the saved artifact and retain native results unchanged.
- A failed task may still have an active remote job; deletion must retain cancellation ownership until stopping is confirmed.
- Cross-origin DELETE and public HTTP task creation must work without weakening authentication or randomness.
- Chinese questions, English questions, mixed technical terms and empty summary questions must not inherit interface language.

## Tasks

- [x] Add regression fixtures and verify failures for partial outcomes, comparison citations, deletion protection, CORS, UUID fallback and question language.
- [x] Extend API types and display partial outcomes and unresolved items in task details/history; preserve legacy retrieval notices.
- [x] Project Agent comparison Markdown citations server-side and render the comparison tab with the existing evidence panel.
- [x] Reject failed local/TACC task deletion until cancellation is confirmed; retain deletion of delivered terminal results.
- [x] Allow authenticated cross-origin DELETE and share cryptographically secure UUID generation across task creation and authentication notifications.
- [x] Clarify Agent/legacy prompt language policy and explain question-driven language in the creation form and API documentation.
- [x] Run focused tests, browser regressions, builds and isolated database suites; inspect the final diff and update this ledger.

## Execution Ledger

- 2026-11-20: Reconfirmed a clean workspace and the existing audit reproductions before editing.
- Ruling: The user's latest language requirement supersedes the proposed interface-language/output_language field; requests remain unchanged and language follows the actual question.
- Ruling: Execute on the user's current branch without commits or extra worktrees; the user requested fixes to this checkout.
- Verification: Backend unittest discovery passed all 261 tests with five isolated databases in a temporary native PostgreSQL 17 container on loopback port 55433. The container was removed in finally; existing application databases and user containers were untouched. Log: `runtime/api-integration-backend-tests.log` (ignored).
- Verification: Frontend production build/typecheck, `verify:review` and `verify:uuid` passed. All six offline Playwright integration tests passed, covering partial details/history, unresolved completed outcomes, native comparison/PDF return, legacy structured comparison/retrieval, question preservation and public HTTP login/submission.
- Documentation: Updated API contract, Agent integration guide and frontend adaptation status; distinguished implemented compatibility fixes from deferred native failed-result presentation and research capabilities.
- Limits: Language checks verify prompt and transport policy, not live model compliance. No real model, arXiv or TACC calls were made. No migration, commit or push was performed; restart the API and Worker and create new tasks to exercise the new language policy.
