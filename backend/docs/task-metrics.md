# Task detail metrics API

Frontend integration, TypeScript examples, polling and display rules:
[Task metrics frontend guide](task-metrics-frontend.md).

Both owned-task detail endpoints return the same additive `metrics` object:

- `GET /api/v1/agent-research/{task_id}` (current research UI).
- `GET /api/v1/tasks/{task_id}` (legacy task UI).

Existing fields, the native Agent result, and the separate evaluation API remain
unchanged. List responses are unchanged. Reads do not enqueue evaluations, run
models, poll GPUs, or contact TACC. The existing task ownership checks run first.
The schema is included in `/openapi.json` as `TaskMetrics`.

## Evaluation

`metrics.evaluation` selects the latest evaluation by creation time and ID, using
the same order as the existing evaluation GET endpoint. It returns evaluation ID,
status, provider, model, rubric/prompt versions, assessment, overall score, weights
and five stable dimensions with `score` and `reason`:

| Dimension | Current weight | Range |
| --- | ---: | --- |
| `grounded_correctness` | 30 | 0-5 |
| `citation_support` | 30 | 0-5 |
| `task_completion` | 20 | 0-5 |
| `analysis_quality` | 15 | 0-5 |
| `clarity` | 5 | 0-5 |

`overall_score` is the existing backend-computed weighted score, range 0-100.
No evaluation, pending/running, failed/skipped, and insufficient evidence are not
zero scores. Their numerical scores remain null. A newer pending version is
returned even if an older version succeeded. Historical scores remain readable
with evaluation disabled; `enabled` and `configured` describe current settings.
This feature does not enable or reconfigure the existing evaluation worker.

## Agent

`metrics.agent` returns `agent_steps`, `model_calls`, `tool_calls`, `input_tokens`,
`output_tokens`, `total_tokens`, and `token_usage_complete` from the persisted
Agent result. These exclude the independent DeepSeek evaluation requests.
Steps and model calls can differ: planning, reflection and summarization can add
model calls. Token counts are provider-reported; missing counts are not estimated
or filled with zero. Queued/running tasks without a saved result return nulls and
`available=false`. Failed tasks with a saved result still expose their usage.

## Model Server

`metrics.model_server` provides task aggregates, sample counts, sources, per-call
readings and the latest snapshot of each GPU returned for this task.

| Field | Unit | Native response fields accepted |
| --- | --- | --- |
| `ttft_ms` | ms | `time_to_first_token_ms`, `ttft_ms` |
| `tpot_ms` | ms/token | `time_per_output_token_ms`, `tpot_ms` |
| `mean_itl_ms` | ms | `mean_itl_ms`, `mean_inter_token_latency_ms` |
| `tokens_per_second` | output tokens/sec | `tokens_per_second`, `output_tokens_per_second` |

Native fields are read from the chat response's top-level `metrics`. Timing scope
follows that server's definition; for the repository's vLLM deployment native
TTFT covers first scheduling to first generated token, not client/network time.
The repository's `metrics.telemetry.request` can supply these explicit fallbacks:

- `server_time_to_first_output_event_ms`: server HTTP entry to first observed
  streaming output event. Normally unavailable for the current non-streaming Agent.
- `server_mean_time_per_output_token_ms`: streaming event approximation of TPOT.
- `server_output_tokens_per_second`: output tokens divided by server request
  duration, including queue/prefill. This is not pure decode speed.

The actual field path is returned in `sources` per request and `source` per
aggregate. Prefill duration alone is not treated as TTFT. TPOT and mean ITL are
separate fields; unknown/bare timing units are not guessed or converted. Missing
timings are not calculated from token totals or Agent elapsed time.

An aggregate is the arithmetic mean of available calls with an identical source.
It is not system-wide throughput or a token-weighted task decode rate. `samples`
reports the number of actual readings. No samples means null, reason `NO_SAMPLES`.
Mixed sources yield no aggregate, reason `MIXED_SOURCES`; individual readings are
still available in `requests` in trace order, with a 1-based `call_index`.
Failed model calls are included as unavailable requests. The counts distinguish
total Agent model calls, model entries observed in the trace and measured calls.

GPU UUID/utilization are read only from `metrics.telemetry.gpu_snapshot.gpus`.
`gpus` at task level retains the latest reading per device with sample time and
call index; each request also retains its own snapshot. Utilization is the NVML
driver sampling window for the whole allocated device at response completion,
potentially including other processes. It is not task-only utilization, a task
average, a peak, memory utilization or GPU memory allocation fraction. GPUs not
reported by the model server cannot be inferred. Missing utilization remains null.

Status is `available` when every reported model call has TTFT, TPOT or mean ITL,
throughput, GPU utilization snapshots and cache token counts; `partial` when only some readings are
available; otherwise `unavailable`. A zero utilization reading is valid data.

### Task cache usage

Both `metrics.model_server` and each entry in `requests` expose:

| Field | Meaning |
| --- | --- |
| `cache_hit_tokens` | Sum of prompt tokens read from cache in measured model requests |
| `cache_query_tokens` | Sum of prompt tokens in those same measured requests |
| `cache_hit_ratio` | `cache_hit_tokens / cache_query_tokens`, range 0-1 (0.4 means 40%) |

The task ratio is token-weighted, not the mean of individual request ratios. For
example, 20 hits out of 100 tokens plus 720 hits out of 900 tokens gives 740/1000
= 0.74, not (0.2+0.8)/2. These are repeated prompt-token reads across this task's
Agent model calls; they exclude independent DeepSeek judging requests and other
users' requests. Cache writes and process-wide cache counters are not counted.

The capture adapter first reads the explicit pair
`usage.prompt_tokens_details.cached_tokens` and `usage.prompt_tokens`. If absent
or invalid, it can use `metrics.telemetry.request.cache_hit_tokens` and
`cache_query_tokens`. The response's reported ratio is recalculated from counts.
Historical traces can use saved `response_metadata.token_usage` with the same
usage pair, or `usage_metadata.input_token_details.cache_read` paired with
`usage_metadata.input_tokens` when raw usage is absent. Invalid/incomplete raw
usage is not repaired using SDK defaults (for example a missing prompt count
defaulted to zero). Each model trace entry is counted once, even when
multiple representations are present. `sources` identifies the pair used.

Only paired non-negative integer counts with hits <= queries are accepted. A
missing cached-token field does not mean zero. Missing/invalid pairs remain null.
Known zero hits with a positive denominator produce a real zero ratio. A known
zero denominator produces a null ratio, not a division by zero or invented zero.

Task-level coverage fields are:

- `cache_measured_model_calls`: number of calls with a valid cache-count pair.
- `cache_usage_complete`: true only when the trace covers all reported Agent
  model calls and every call has valid cache counts.
- `cache_unavailable_reason`: `CACHE_USAGE_NOT_AVAILABLE` when there are no
  valid observations, `ZERO_CACHE_QUERY_TOKENS` when their sum is zero, otherwise
  null.

If coverage is incomplete, the totals and ratio describe only paired observed
requests, not the full task. Unknown calls are not filled with zero and their
input tokens are not added to the ratio denominator. When no calls are measured,
all three cache values are null and completeness is false. The existing
`token_usage_complete` describes ordinary token counts and does not replace this
separate cache coverage flag. No database migration is needed.

## Capture and deployment

Backend-managed TCloud jobs stage a backend-owned `run_job.py` wrapper alongside
the unmodified TACC entrypoint as `research_job.py`. Before actual research runs,
the wrapper installs an adapter for `ChatOpenAI._create_chat_result` that preserves
only whitelisted server metrics in the AI message's
`response_metadata.server_metrics` (`backend-model-metrics-v1`). The existing Agent
trace and result JSON persistence carry it back; no database migration is needed.
Bootstrap/failure commands do not require the Agent SDK. Optional capture failure
does not fail research. No Agent, model-server or frontend source is changed.

Deploy the updated backend and restart the API and dispatch worker. Capture applies
to newly staged TCloud jobs. Already submitted jobs and historical results are not
backfilled. Other transports can read the same captured trace format but do not
automatically install this TCloud adapter. The model server must already return
the requested telemetry; a third-party API without it yields unavailable values.
Cache statistics can still be available from standard usage when timing/GPU
telemetry is absent. Old tasks only gain cache metrics if their saved trace already
contains the explicit counts; missing history is not reconstructed from totals.

## Abbreviated response example

```json
{
  "metrics": {
    "schema_version": "task-metrics-v1",
    "evaluation": {
      "status": "succeeded",
      "assessment": "scored",
      "overall_score": 80,
      "dimensions": {
        "grounded_correctness": {"score": 4, "reason": "Supported by the cited pages."},
        "citation_support": {"score": 4, "reason": "References support the main claims."},
        "task_completion": {"score": 4, "reason": "Requested points are covered."},
        "analysis_quality": {"score": 4, "reason": "Conclusions are qualified."},
        "clarity": {"score": 4, "reason": "The answer is clearly structured."}
      }
    },
    "agent": {
      "available": true,
      "agent_steps": 8,
      "model_calls": 10,
      "tool_calls": 7,
      "input_tokens": 12000,
      "output_tokens": 2000,
      "total_tokens": 14000,
      "token_usage_complete": true
    },
    "model_server": {
      "status": "partial",
      "model_calls_total": 10,
      "observed_model_calls": 10,
      "measured_model_calls": 9,
      "cache_hit_tokens": 6000,
      "cache_query_tokens": 10000,
      "cache_hit_ratio": 0.6,
      "cache_measured_model_calls": 9,
      "cache_usage_complete": false,
      "cache_unavailable_reason": null,
      "ttft_ms": {
        "mean": 120,
        "samples": 9,
        "source": "metrics.time_to_first_token_ms",
        "unavailable_reason": null
      },
      "gpus": [
        {"uuid": "GPU-example", "utilization_percent": 75,
         "sampled_at": "2026-11-22T12:00:00Z", "call_index": 9}
      ]
    }
  }
}
```

## Verification

Run backend tests with `python -m unittest discover -s tests -v`.
`test_task_metrics_postgres.py` requires an isolated `AGENT_TEST_DATABASE_URL`
accepted by the existing fixture guard. Do not point it at application data.
To test the actual model SDK without network requests, use the installed Agent
Python with backend `src` on `PYTHONPATH` to run
`python -m unittest discover -s backend/tests -p test_model_telemetry_sdk.py -v`.
The test uses an in-memory HTTP transport and does not create a research job.
