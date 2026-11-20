# Agent Reading Context Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline and test-driven-development. No commits, pushes, service operations or real model calls.

**Goal:** Prevent accumulated original PDF readings from exhausting model context while preserving evidence and audit history.

**Architecture:** Archive older original readings only in the model view; preserve summaries and the latest original reading. Keep canonical messages and evidence unchanged, and allow archived chunks to be read again.

**Tech Stack:** Python 3.12, LangChain messages, LangGraph, pytest, Ruff.

**Spec:** docs/superpowers/specs/2026-11-19-agent-reading-context-design.md

## Global Constraints

- Keep context configuration and output reserve unchanged.
- Preserve authorization, citations, lifecycle and transport behavior.
- Preserve existing uncommitted documentation and private environment files.
- Use only synthetic papers and offline scripted models.

## Review Focus

- Archived pages remain readable without repeating visible pages.
- Original citations and audit observations remain unchanged.
- Parallel and reused tool-call IDs retain correct pairing.
- Changed views invalidate incompatible usage anchors.
- Unshrinkable input still fails before a model call.

## Task 1: Reproduce and fix bounded reading views

**Files:** agent/context.py, agent/baseline.py, agent/tests/test_bounded_context.py.

**Interfaces:** Add prepare_bounded_context with the existing policy signature; PreparedContext carries archived original IDs and an archive count; RunLog hands archived IDs to read_paper.

- [x] Add and run failing regressions for large readings and archived-page restoration.
- [x] Implement bounded projections and restoration without changing canonical messages.
- [x] Cover reserve boundaries, no-op limits, malformed observations, parallel calls, usage anchors and unshrinkable input.
- [x] Run context, baseline, local-source and dispatch tests.

Expected: targeted tests pass without model or database access.

## Task 2: Verify integration and document reacceptance

**Files:** docs/agent-backend-integration.md, docs/agent-transport-acceptance.md.

- [x] Document archival semantics, safety limits and fresh-task reacceptance.
- [x] Run full Agent tests, backend round-trip coverage, Ruff and diff checks.
- [x] Obtain a fresh read-only review and address material findings.
- [x] Report exact offline results and the remaining real-model acceptance step.

Expected: no budget, source, protocol or ownership regressions; no commit or push.

## Verification record — 2026-11-19

- RED: both initial reproduction tests failed with context_limit before implementation.
- Targeted context/baseline/local/dispatch tests: 128 passed.
- Full Agent suite: 228 passed, 4 skipped; synthetic inputs and scripted models only.
- Backend contract suite: 14 passed.
- Separate-process PDF round-trip: 1 passed. Initial sandbox run failed at lock-file flush with PermissionError; approved unsandboxed retry passed without modifying transport code.
- Ruff check and format check passed for all three changed Python files; git diff --check passed.
- Independent read-only review found no concrete issues.
- The real task hit step_limit while alternating reads of pages 9–10 and 11. The follow-up regression reproduced a second restore of the same original. Agent now allows one restore per chunk, finalizes early on a restore-only stall, and uses the last available step to finalize if evidence exists.
- Follow-up offline verification: 230 Agent tests passed, 4 skipped. The 14 backend bridge contract tests, Ruff and diff checks passed. The final request test verifies that it omits tools while retaining the matched tool history.
- Real-model regression, task output and citation quality remain pending user execution.
