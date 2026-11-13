# Backend package layout

## Scope and design

The user requested a clearer project structure, focusing on the flat backend/src/app directory. This is an organizational refactor: keep HTTP/OpenAPI contracts, database schema, persistence and execution rules unchanged. Continue in the current workspace and preserve the unrelated uncommitted progress roadmap. Do not commit, push, restart running user services or submit model/source requests.

Use packages by responsibility rather than adding repository/service abstractions around existing functions:

- app.api: health, papers, tasks and imports HTTP routes, schemas, response views and router composition.
- app.papers: PDF storage, parsing, parse lifecycle and evidence reading.
- app.research: model client, LangGraph workflow, retrieval and result validation.
- app.sources: arXiv client/transport, shared source access and import persistence.
- app.tasks: task submission/query service and task execution lifecycle.
- app.workers: mock, parser, research and import process implementations.
- Keep app.db, app.config, app.errors and app.main at their existing infrastructure locations. Keep the four existing root Worker modules only as small command launchers, preserving python -m app.worker/parser_worker/runner_worker/import_worker. Internal callers use the new implementation modules directly.

Split the mixed API module into health/papers/tasks routes. Retain original router error metadata and registration order; keep the source-import router's own response metadata. Do not change function names, endpoint paths or public schemas.

Update every application import and runtime regression import/mock target without alias tricks or sys.modules redirects. Historical implementation docs may retain original file names as dated evidence; current startup/structure guidance must show current paths.

Subprocess paths require explicit handling: parser worker finds pdf_parser.py in app.papers rather than next to itself and keeps its child cwd at backend/src; arXiv transport sets the sanitized child PYTHONPATH to backend/src after moving and preserves inherited cwd behavior. Configuration and Alembic roots stay unchanged because config.py/main.py remain at the root.

## Verification

Capture the existing generated OpenAPI document before changes and compare after relocation. Add focused ignored runtime checks for package ownership, all-module import without configuration/network side effects, original command forwarding, original settings paths and supervised-child paths. Observe these checks fail against the flat tree first. Run the existing 190 offline regressions, backend bootstrap, PDF core/parser timeout checks and syntax/whitespace checks. No real PostgreSQL mutation or paid/live API call is part of this refactor.
