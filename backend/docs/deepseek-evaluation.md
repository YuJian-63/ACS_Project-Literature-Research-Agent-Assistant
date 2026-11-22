# DeepSeek result evaluation

The backend can evaluate saved Agent research without changing its answer, success/failure state or execution budget. Agent and frontend implementations are unchanged. Scores are independent model assessments within the supplied evidence, not benchmark accuracy or a guarantee of factual correctness. Real calibration against human-reviewed summary, QA and review examples remains required before relying on these scores for comparisons.

## Enable explicitly

Apply the additive migration with the application's existing environment, then configure these values in the private backend `.env`:

```dotenv
EVALUATION_ENABLED=true
EVALUATION_BASE_URL=https://api.deepseek.com
EVALUATION_MODEL=<model-id-available-to-your-account>
EVALUATION_API_KEY=<private-api-key>
```

The model must support chat completions with JSON output. Choose an actual model ID from your account; the application does not assume a permanently valid model name. API credentials remain in the backend and are never sent to TACC or included in responses. JSON-mode reference: https://api-docs.deepseek.com/guides/json_mode/ . The adapter requests disabled thinking, non-streaming JSON and no tools.

```sh
cd /home/acs/ACS_Project-Literature-Research-Agent-Assistant/backend
.venv/bin/alembic upgrade head
.venv/bin/alembic check
.venv/bin/python -m app.evaluation_worker --once
```

Restart the API and research runner after configuring them. The API and research runner create requests; the separate evaluation worker processes them. With the default `EVALUATION_ENABLED=false`, existing research behavior remains unchanged. Enabling does not scan or bill historical tasks. Only newly delivered results are automatically queued; explicit POST requests can evaluate history.

For a persistent ECS service, install the example as root:

```sh
install -m 644 backend/ops/acs-evaluation.service /etc/systemd/system/acs-evaluation.service
systemctl daemon-reload
systemctl enable --now acs-evaluation.service
systemctl is-active acs-evaluation.service
journalctl -u acs-evaluation.service -n 50 --no-pager
```

Run the install command from the repository root, after deployment and private configuration. The unit is wanted by `acs-runner.service` and has `PartOf=acs-runner.service`: the existing deployment's runner stop/start also stops/starts evaluation around migrations. Evaluation failure does not stop the research runner. If your service names or repository path differ, adapt the example. No deployment script, production configuration or running service is changed by this patch.

To pause external scoring, stop the evaluation service, disable `EVALUATION_ENABLED` in the shared backend configuration and restart the API/runner. Completed reports remain queryable. Pending records are retained. A change to the model, rubric, prompt or evaluation limits creates a new configuration identity; the worker marks old queued configurations `EVALUATION_CONFIG_CHANGED` instead of silently running them with different settings. Trigger a new evaluation explicitly for such a record.

## Rubric and report

| Dimension | Weight | Focus |
| --- | --- | --- |
| grounded_correctness | 30% | Claims, numbers and conclusions consistent with available evidence |
| citation_support | 30% | Evidence actually supports the associated claims and references can be located |
| task_completion | 20% | Answers the user's question and requested subparts |
| analysis_quality | 15% | Synthesis, comparable conditions, contradictions, limitations and uncertainty |
| clarity | 5% | Clear organization and language, without rewarding verbosity |

Dimensions use scores 0..5 with reasons. The backend computes `sum(score * weight / 5)`, rounded to one decimal, out of 100. Zero is absent/fundamentally wrong; 1 severe deficiencies; 2 substantial gaps; 3 adequate with identifiable gaps; 4 strong with minor gaps; 5 excellent within the supplied evidence. An `insufficient_evidence` report has null scores and null overall score. It is still a successfully generated report, not a failed research task.

Summary focuses on motivation/method/findings/limitations; QA on a direct, supported answer and unknowns; review on cross-paper coverage/synthesis and comparable experimental conditions. No automatic score caps, pass/fail threshold or low-score research resubmission are implemented. Reasons and suggestions follow the question's language through the judge instruction; multilingual adherence needs live acceptance testing.

The input includes all native Agent citations, including external sources absent from the display citation table. Local display keys remain `C1`, etc.; other native citations receive stable `E` keys. Structural checks report recognizable unresolved and unused citation references. Local original files are restricted to papers already associated with the task owner. Hash-verified cited pages can be read in a bounded subprocess with a minimal environment; no backend chunks are generated. External URLs are not fetched. Scanner/OCR limitations, missing files, changed hashes and page limits are disclosed.

`evaluation_scope=evidence_only` means only returned excerpts were available. `original_pages` means some independent cited-page context was available; it does not mean every citation or the complete paper was checked. Per-citation statuses are `matched`, `not_found` or `unavailable`; a failed text match alone is not proof of fabrication. The exact evidence snapshot and digest are stored and reused on retries. The final request digest, actual provider model, nullable token usage and elapsed time are retained for audit.

## API

Both routes require the existing login session and task ownership. POST additionally requires the existing trusted Origin and CSRF token.

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/api/v1/tasks/{task_id}/evaluation` | Latest report/status, or `not_requested` |
| GET | same route with `?evaluation_id=<uuid>` | A historical version belonging to this task |
| POST | `/api/v1/tasks/{task_id}/evaluation` | 202; enqueue history, reuse an existing version or retry a failure within its attempt budget |

GET responses include the ID, task ID, feature state, status, model/rubric/prompt versions, input/evidence digests, attempt count/budget, sanitized error code, report, usage and timestamps. Internal input snapshots, file paths, API URL/configuration and credentials are not returned. Historical IDs can be obtained from previous POST/GET responses. A missing task or another user's task returns 404. An unknown evaluation ID on an owned task also returns 404. There is no mutation through GET and no automatic historical sweep.

Example successful report fragment:

```json
{
  "status": "succeeded",
  "report": {
    "assessment": "scored",
    "overall_score": 74.0,
    "rubric_version": "research-v1",
    "evaluation_scope": "evidence_only",
    "dimensions": {
      "grounded_correctness": {"score": 4.0, "reason": "..."},
      "citation_support": {"score": 3.5, "reason": "..."},
      "task_completion": {"score": 4.0, "reason": "..."},
      "analysis_quality": {"score": 3.0, "reason": "..."},
      "clarity": {"score": 4.0, "reason": "..."}
    }
  }
}
```

Full reports also contain a summary, issues with severity/code/message/citation keys/literal answer excerpt, suggestions, weights, evidence/reference checks and limitations. The future frontend should render report text as untrusted content. Existing research/result API shapes are unchanged.

## Budgets, recovery and errors

- Default allowance: 30 new evaluation versions per user per UTC day, at most 3 attempts per version. Independent `evaluation_daily_quotas` rows reserve allowance atomically; deleting a task does not refund it. Repeated requests reuse an identity; retrying does not reset attempts. Results automatically skipped for lack of allowance can be explicitly requested once allowance recovers, reserving a slot on the current day. This bounds calls to at most 90 per user's daily reserved versions, although queued retries can run on later days. There is no global paid-API allowance or token-price estimator.
- Default request budget: 64,000 UTF-8 bytes including the system prompt, full answer, all excerpts and available page context. This is a conservative byte bound, not a provider tokenizer or a guarantee for an arbitrarily configured model context. Overflow fails explicitly; it is not silently truncated. Output is limited to 4,096 tokens and 262,144 response bytes.
- Up to 12 distinct original cited pages are read, with a 20-second subprocess timeout; individual page text above 16,000 UTF-8 bytes is omitted with a disclosed limitation. Original PDF input keeps the existing 50 MB limit. On POSIX systems extraction also has memory/CPU limits.
- Provider timeout defaults to 90 seconds. HTTP 429/5xx, timeouts, network failures and malformed structured output receive bounded exponential retries. Authentication/request errors, output truncation and input/response overflow require operator attention. Error responses, credentials and HTTP exception text are not stored or logged.
- Work is leased durably. Expired leases are recovered, exhausted attempts become failed, and stale workers cannot save evidence or reports. At-least-once execution means a process failure after a provider request can repeat a paid call; the attempt limit still applies. Provider billing cannot be made transactionally exactly-once.
- Invalid citation references or invented issue excerpts reject a judge response. Insufficient evidence produces a null score; failed Agent execution without usable results produces `skipped/NO_USABLE_RESULT`, not zero. Useful partial Agent output remains evaluable.
- Task deletion cascades evaluation history. No external call is made while holding a database transaction. Deleting a task cannot cancel an HTTP request already in flight, but stale completion cannot resurrect the deleted task.

## Verification

Run the backend suite from `backend/`:

```sh
.venv/bin/python -B -m unittest discover -s tests -v
```

Database tests opt in through `AGENT_TEST_DATABASE_URL`, which must point to a disposable loopback `agent_bridge_tests` database and will be truncated. `test_evaluation_postgres.py` covers queue identity, ownership/CSRF, automatic enqueue, leases, retries, versions, deletion and the full worker path with a mocked HTTP provider. `test_evaluations.py` covers rubric math, strict JSON validation, budgets, error redaction and real PDF page extraction. Real API credentials and human scoring calibration are deliberately separate acceptance steps.
