# Research and evaluation limits

Agent research receives `min(AGENT_MAX_STEPS, 32 + 8 * N)` steps. `N` is the selected paper count, plus `AGENT_SEARCH_MAX_PAPERS` when search is enabled, capped at 20. `AGENT_MAX_STEPS` defaults to 200 and accepts values from 1 to 200. Both unified research and legacy summary/QA/review submissions use this policy. A single selected paper without search receives 40 steps; five receive 72; twenty receive 192. Task duration and output/context token limits keep their existing policies.

`USER_DAILY_TASKS` defaults to 50 newly created research tasks per user per UTC day. Idempotent replays do not create tasks or consume additional allowance. The existing active-task limit is independent. Research allowance still counts existing task records; deleting research history can reduce its daily count.

DeepSeek scoring defaults to `EVALUATION_TIMEOUT_SECONDS=180`, `EVALUATION_DAILY_LIMIT=50` and `EVALUATION_EVIDENCE_TIMEOUT_SECONDS=60`. All distinct cited original pages are eligible for extraction; there is no page-count setting. PDF identity verification, subprocess isolation and memory/byte/input/output budgets still apply. See [evaluation operations](deepseek-evaluation.md) for retries, evidence limitations and the independent evaluation allowance.

## Applying the settings

1. Update any explicit values in the private backend `.env`; environment values override these defaults. Remove the obsolete `EVALUATION_MAX_ORIGINAL_PAGES` line.
2. Run `alembic upgrade head` and `alembic check` from `backend/` before enabling tasks above 100 steps. Revision `20261122_0015` raises the database constraint to 200 and preserves existing task budgets. Downgrade to 0014 is rejected while tasks above 100 steps exist; no historical budgets are silently rewritten.
3. Restart the API, research worker and evaluation worker using the same configuration.

New research submissions receive the new step budgets. Existing tasks keep their saved budgets. Evaluation settings are versioned: an old queued configuration is rejected with `EVALUATION_CONFIG_CHANGED`; explicitly request a new evaluation version after changing these settings. The old 12-page extraction cap is removed even when private configuration still contains its obsolete setting.
