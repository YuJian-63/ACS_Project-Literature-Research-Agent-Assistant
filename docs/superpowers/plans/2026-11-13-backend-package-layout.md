# Backend Package Layout Implementation Plan

**Goal:** Organize the backend into API, paper, research, source, task and worker packages while preserving observable behavior and startup commands.

**Architecture:** Keep infrastructure and thin CLI launchers at app root, move implementation modules into responsibility-based packages, split the mixed HTTP routes and update all internal imports. Preserve the pre-refactor OpenAPI document and verify supervised subprocess roots explicitly.

**Spec:** docs/superpowers/specs/2026-11-13-backend-package-layout.md

## Tasks

- [x] Capture baseline OpenAPI and add failing package/import/command/path checks under the existing ignored runtime convention.
- [x] Relocate implementations, split routes, update imports and supervised child paths, and retain four tiny legacy command launchers.
- [x] Update active structure/startup documentation and runtime regression imports/mock targets.
- [x] Run focused checks, the existing offline regressions, bootstrap and parser checks; review semantic diff, syntax and whitespace.
- [x] Record verified results and limits; leave changes uncommitted and running services untouched.

## Ledger

- The only preexisting uncommitted file is docs/superpowers/plans/2026-11-13-progress-and-next-roadmap.md; preserve it.
- Routine layout decision within the user's requested refactor: use cohesive packages instead of only moving every file into generic service/util folders. Keep existing launch commands to avoid forcing terminal changes solely for organization.
- Execute locally; no delegation or independent reviewer is authorized. Distinguish local scoped review from independent review.
- Baseline: 30 Python files, 26 directly at app root. Captured OpenAPI for all 13 paths. Seven focused checks initially produced 26 failures and six import errors for the absent layout; baseline OpenAPI, settings paths and import-without-configuration checks already passed.
- Implementation: relocated 22 modules, split the mixed API into three route modules plus shared pagination and a router compositor, and retained four five-line CLI launchers. app root now has eight Python files. Updated ignored runtime imports and mock targets rather than adding module alias redirects.
- Focused checks now pass, including exact OpenAPI comparison, all-module side-effect checks, four original command forwarders and an actual sanitized PDF parser child. The combined existing 190, bootstrap 12 and focused seven checks passed: 209 tests total.
- Windows patch application exceeded the command-line length when API additions and all runtime updates were passed together; no patch from that invocation was applied. Applied bounded per-file patches instead. Four runtime from-app imports required explicit package aliases; adjusted those imports only and then completed the green regression run.
- Added an eighth focused check for actual TestClient routing with a mocked engine: health/request ID, migration-ready/not-ready, invalid task body, disabled-source error and unknown path; no real connection or model request. Final combined run: 210 tests passed across 14 suites (190 prior + 12 bootstrap + eight focused).
- PDF core checks and the parser deadline-boundary check passed separately. The actual relocated parser child also successfully parsed a minimal one-page synthetic PDF under the sanitized environment. The malformed-PDF fixture prints its expected EOF diagnostic.
- Semantic review: normalized import rewrites and the two explicit child-path adjustments match ASTs for all 21 non-API relocated modules plus config/main; all 12 original API functions match their split counterparts exactly. All 44 current source Python files parse successfully; generated OpenAPI remains exactly equal for all 13 paths, including response metadata and operation IDs.
- Local scoped review found no blocking issue. Application import scan found no stale flat-module imports. Database migrations/schema, dependency declarations/lockfile and frontend remain unchanged. The frontend already separates pages/components/hooks/api/lib, so no unrelated frontend rearrangement was made.
- Current backend README documents the new tree and internal import migration. Existing API factory and four original Worker commands are preserved; direct internal imports must use their new packages. Shared config paths, database paths and storage semantics are unchanged. Restart API and active Workers in their original terminals before subsequent integration work; the refactor did not restart or stop user processes.
- Scope: no live upstream/model calls, real business database mutations, credentials changes, dependency downloads, commits or pushes. Full native database and paid-model acceptance were not rerun for a directory-only refactor. Runtime verification scripts remain ignored under the existing convention; formal tracked tests/CI remain separate follow-up work. The preexisting progress roadmap was preserved.
