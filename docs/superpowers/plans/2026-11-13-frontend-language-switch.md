# Frontend Language Switch Implementation Plan

**Goal:** Provide persistent Chinese/English UI switching without changing research data or execution.

**Spec:** docs/superpowers/specs/2026-11-13-frontend-language-switch.md

## Tasks

- [x] Record current Chinese behavior and add focused locale, catalog and browser acceptance checks.
- [x] Add the catalog/store, localized Ant Design wrapper and accessible top-bar language selector.
- [x] Translate pages/components, validation/status/error messages and dates while preserving route/form/request state.
- [x] Run typecheck/build and isolated bilingual browser checks plus existing frontend regressions; inspect mobile layout.
- [x] Document scope and verification evidence, leave changes uncommitted and user services untouched.

## Ledger

- Start from clean commit e3e6943. Apply the existing frontend design and React best-practice guidance; retain the product's layout and use a small separate language control.
- Source-message keys keep the two-language catalog close to the existing copy. Extract literal/interpolated UI strings without rewriting business expressions; explicitly move static translated labels/columns to render-time factories.


## Verification — 2026-11-13

- `npm.cmd run build --prefix frontend`: TypeScript application/tooling checks and production build passed; no new dependency.
- `node runtime/verify-i18n-core.cjs`: Chinese default, valid/invalid saved preferences, blocked localStorage, subscriptions, idempotent locale updates, interpolation, English singular forms and catalog placeholder checks passed. The initial check failed before the locale store existed.
- `node runtime/verify-frontend-core.cjs`: existing normalization, selection counts, submission signatures and PDF upload boundaries passed.
- `runtime/browser-venv/Scripts/python.exe -B runtime/verify-i18n-ui.py --legacy`: isolated Chromium checks and the existing frontend browser regression passed. Covered the five pages, live table headers/statuses, existing errors and backend events, custom and Ant Design form validation, refresh persistence, blocked storage, original source/model content, draft/selection/budget retention, unchanged request body/idempotency key, and continued task polling without restart. Mobile checks passed at 360px and 390px.
- `runtime/browser-venv/Scripts/python.exe -B runtime/verify-search-resilience-ui.py --legacy`: existing search/import checks passed, including explicit search, paging, retained results, timeout/rate-limit cooldowns, no automatic retry, imports, stale-response fencing, reload and mobile layout.
- `git diff --check`: passed. Desktop task details and mobile search screenshots were inspected; English single-item count labels were corrected and rechecked.

Browser checks used local fixture interception and isolated Vite servers with an unreachable proxy fallback. They did not call the user's backend, database, arXiv or models. Expected injected HTTP 503 failures appeared in the legacy browser console; its assertions passed with no JavaScript errors. Existing user services were not restarted. The temporary scripts, screenshots and logs remain under ignored `runtime/`, consistent with the project's current convention; they are not a tracked CI suite.

Implementation and usage are documented in `frontend/README.md`, section 8. Changes remain uncommitted.
