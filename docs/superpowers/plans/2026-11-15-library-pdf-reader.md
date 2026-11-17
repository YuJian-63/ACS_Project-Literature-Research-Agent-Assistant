# Library PDF Reader Implementation Plan

**Goal:** Read and switch between library PDFs without leaving the current page.

**Architecture:** Open a reading workspace from a library title. Wide screens pair a compact, selectable library list with a PDF reader; small screens prioritize the reader and offer a paper selector and a return action. Fetch PDFs through the existing authenticated API, then embed a temporary browser object URL. Cancel obsolete requests and revoke URLs on switching, closing, or leaving the page.

**Tech Stack:** React, TypeScript, Ant Design, native browser PDF viewer, existing Axios session handling, Playwright.

**Spec:** The existing visual system in DESIGN.md and the interaction requirements below.

## Interaction requirements

- Keep query, filters, pagination and research selection when opening or closing a PDF.
- Provide paper switching, focused reading, return to library, loading, retry, and an explicit external-open fallback.
- Show actual titles and metadata. Provide Chinese and English controls, keyboard focus, and layouts from 320px upward.
- Load documents only on demand. Reuse file ownership checks and session expiry handling; do not add a public file endpoint, dependency, or database migration.
- Cancel stale downloads and release object URLs; a late response must never replace the currently selected document.
- A browser without an embedded PDF viewer can use the external-open link. The browser supplies PDF paging and zooming.

## Implementation

- [x] Add an offline browser check for library preservation, switching, stale responses, URL cleanup, failures, authentication expiry and responsive bilingual layouts; confirm it fails before implementation.
- [x] Add authenticated file loading and focused reader/list components, then connect library title actions.
- [x] Add responsive styles and translated labels, preserving the existing language-switch improvements.
- [x] Run the reader check, existing search checks, frontend build and review checks; inspect desktop/mobile screenshots.

## Validation results

- Frontend production build and review checks passed.
- The dedicated browser check passed using installed Edge in headless mode, with locally generated PDF bytes and mocked APIs. Confirmed actual native PDF rendering in desktop/mobile screenshots, language changes, document switching, query/page/selection preservation, focus return, request cancellation, URL cleanup, invalid-file recovery and authentication expiry.
- Existing search browser regression was attempted: its broad alert selector can match both error and retained-results notices; another run hit the existing narrow-screen width assertion. No search page behavior or assertions were changed for this feature.
- No external API calls, model calls, email, database migrations or new dependencies.
