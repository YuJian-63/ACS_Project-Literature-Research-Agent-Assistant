# Paper search experience

**Goal:** Give paper metadata and abstracts more reading space, collapse abstracts by default, support page jumps and return readers to the new results, and sort the full search upstream.

**Design:** Preserve the green research workspace. Use a wider result column and compact import history, stacking history below results on smaller desktops. Abstracts show three lines with a keyboard-accessible expand/collapse button. Offer 10/25/50 papers per page, defaulting to 10, within the existing maximum start offset of 1000 (up to 101/41/21 pages respectively). Display the accessible range and provide numbered pagination and a page jump. Changing page size resets to page one and preserves the query and sort; pagination uses the successful response's limit so failed changes cannot relabel old results. Scroll and move focus to the result heading after a successful page change, never on failed requests or history refresh. Sort by relevance, publication date or last update; date sorts allow both directions and reset to page one. Preserve the last successful page on request failure.

**Implementation:**

- [x] Add sorting validation, upstream parameters and cache-key separation in arxiv.py, arxiv_transport.py, access.py and api/imports.py, with offline backend tests.
- [x] Update SearchPapersPage, the typed API client, bilingual messages and responsive styles. Keep import polling and cooldown behavior.
- [x] Verify collapse/expand, pagination, scrolling, sort requests, failure recovery and bilingual layouts with mocked browser APIs; run the production build and update the API contract and design notes.

No database migration or new dependency is required. Do not commit changes unless requested.

**Validation:** Production build, verify:review, search-browser.py, auth-browser.py, four sorting/pagination unit tests and the existing 28 arXiv checks passed. Search browser checks cover both locales at 320, 390, 768, 1190 and 1440px, 10/25/50 sizes with matching page jumps and caps, mobile jump availability, sort/size preservation, success-only scrolling, failed-page and failed-size retries, and empty-page navigation. Backend checks exercise 50-entry Atom parsing, transport bounds, cache isolation and HTTP size validation. Browser and backend checks use fixtures and do not contact arXiv or a model. Desktop/mobile screenshots are in ignored runtime/search-preview.

The existing workspace-browser.py could not reach its page checks because its API fixture does not handle /api/v1/auth/me. Its source was left unchanged; this broader script is not counted as passing.
