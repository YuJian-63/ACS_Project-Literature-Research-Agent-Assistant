# Literature Research Workspace

## Direction

The application follows the approved A+B/C design in docs/design-proposals/2026-11-14/refined.html. A provides the green research workspace, B provides manuscript reading, and C provides comparison linked to source evidence. The implementation lives in frontend/src; the HTML proposal is a visual reference only.

## Visual language

| Role | Token / value | Purpose |
| --- | --- | --- |
| Ink | --ink / #213a38 | Main text and headings |
| Muted | --muted / #536e69 | Supporting copy and metadata |
| Accent | --accent / #176352 | Primary actions, selected navigation and citations |
| Line | --line / #dbe5e1 | Quiet separators and table boundaries |
| Background | --bg / #f0f5f4 | Sidebar and outer surfaces |
| Soft surface | --soft / #e7f0ec | Selected and supporting surfaces |

Use white working surfaces, thin rules and restrained corner radii. Reserve elevation for overlays. Status indicators include text as well as color. Keep one clear primary action per context: start research, search, upload or submit.

The normal desktop shell uses a 208px sidebar, a compact breadcrumb/language bar and a white content area. Tables and forms use a sans serif face; page headings and manuscript text use a serif face. Reading content has a measured line length instead of stretching across the workspace. Use spacing to separate sections before adding containers.

## Fonts

The application serves Research Sans and Research Serif Latin subsets locally from frontend/src/assets/fonts. They derive from Noto Sans SC and Noto Serif SC, respectively; the accompanying OFL.txt contains the license. The subsets contain U+0000–024F only. CSS unicode-range deliberately leaves arbitrary Chinese and other scripts to system fallback fonts (Noto Sans SC / Microsoft YaHei and Noto Serif SC / Songti SC / SimSun). Do not use the design proposal's small Chinese character subset to render arbitrary research content. No remote font service is required.

## Page structure

- Library: compact upload section, parsing details on demand, filters, selectable paper table and research action. Source, page count and parsing state remain visible.
- Search: explicit search submission, results and persistent import history in separate columns when space permits. Retain the previous successful results and error recovery behavior.
- New research: source selection and research question alongside a submission summary. Literature review resources remain automatically allocated by the backend.
- Research history: filters, question/type, status, source count, execution mode and date. Each record opens its saved task.
- Research result: task status and question above the result tabs. Reading, comparison and execution events have separate views. Execution statistics, input papers and technical details belong with execution events.

## Results and evidence

ArtifactView renders the saved Markdown; it does not replace it with demo copy. Its outline comes from actual headings. Known [C1]-style markers become citation controls, while code and unknown markers stay literal. Keep the Markdown safety rules: no embedded HTML or images, only supported safe links.

ComparisonView uses the actual backend columns and rows. Resolve paper names from the input papers, then citations; show a readable fallback instead of an ID if neither is available. Missing values mean “Not reported”, not zero. A cited cell selects the corresponding excerpt in EvidencePanel. The panel displays the exact saved quote, paper title and page, with a link to the local PDF at that page. Never invent confidence scores, findings, page counts or citations.

## Responsive behavior

- Above 1190px: full sidebar and wider working area; search and import history share a row.
- At 1190px and below: narrower sidebar and tighter page spacing.
- At 1000px and below: source evidence opens in a modal drawer; input papers remain available there. Closing returns keyboard focus to the citation or source button.
- At 760px and below: navigation becomes horizontal, forms stack, and comparison uses a paper selector with dimensions listed vertically. Data-heavy library/history tables retain contained horizontal scrolling.
- The application supports a minimum viewport width of 320px. Keep long titles and manuscript text wrapping inside their own regions.

## Language and states

Account entry uses a shared AuthLayout for sign-in, registration, email verification, password recovery and AuthGate loading/error states. The desktop layout pairs a pale sage research introduction with a white form surface; at 760px and below, the form appears first and the introduction becomes compact. Keep the existing local fonts and green accent, visible field labels, keyboard focus and explicit retry actions. Authentication styles live in frontend/src/auth/auth.css. The paper illustration is decorative and contains no research results.

Use the existing locale provider and message catalog for interface text. Preserve the user's saved language choice. Switching interface language translates controls and known generic result titles; it does not translate saved research questions, paper titles, generated Markdown, quotations or comparison values.

Loading, empty, running, failed, mock and no-citation states must stay explicit. Preserve query-error recovery, task polling, idempotent submission and import history. Mock results keep their visible warning. Missing statistics stay “—”; do not fabricate data to fill the design.

Use semantic headings, labeled controls, visible focus, keyboard-operable citations, modal focus containment, Escape to close and reduced-motion preferences. Do not rely on color alone to communicate task status.

## Validation

Use npm.cmd run build and npm.cmd run verify:review in frontend. From the repository root, run frontend/checks/workspace-browser.py with a Python environment containing Playwright and Chromium. Set WORKSPACE_PREVIEW_URL to the running Vite URL if it differs from http://127.0.0.1:5191. The check intercepts application APIs; it does not submit real research tasks or contact arXiv or a model. It covers citation/evidence interactions, literal code, comparison, language persistence, activity, running/failure states and page overflow at 390px, 768px and 1440px. Runtime screenshots are development evidence, not product data.
