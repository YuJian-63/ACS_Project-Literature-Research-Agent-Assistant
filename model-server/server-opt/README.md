# `server-opt`: Qwen vLLM model-server optimization package

This directory is the model-server artifact for the Qwen vLLM optimization study. It contains the public-runtime server launcher, the deterministic evaluation clients and workloads used by the study, environment/configuration files, selected result summaries, and the English model-server report.

The final submitted setting is **C=4 with `max_num_batched_tokens=8192`**. It is a throughput-oriented setting for the long-input concurrent workload. It is not a claim that every single-request workload will be faster.

## Repository integration

The application model-management page and `scripts/verify-model-server` still deploy the original [`server/`](../server/) package, whose scheduling budget is 4096. Adding this directory does not switch that default. To use this optimized service, submit it manually, wait for readiness, and select **Custom endpoint / 指定服务地址** when creating a research task. Use the current job's `SERVICE_BASE_URL`; the Agent CPU job must be able to reach it on the TACC network. The application does not stop manually submitted services: cancel your GPU job after its consumers finish. See the [model-server overview](../README.md) for both deployment paths.

## Final server configuration

```text
model                         qwen3.8-27b
runtime                       public course vLLM
vLLM                          0.26.0
PyTorch                       2.11.0+cu128
dtype                         bfloat16
tensor_parallel_size          2
GPU                           2 x NVIDIA RTX 3090
max_model_len                36864
max_num_seqs                 4
max_num_batched_tokens       8192
gpu_memory_utilization        0.9
enable_prefix_caching        true
attention backend             auto -> FlashAttention v2
tool-call parser              qwen3_coder
```

`max_model_len=36864` is the total context limit for one request: prompt, system message, tool schemas, chat-template tokens, and generated output are all included. `max_num_batched_tokens=8192` is the scheduler budget per iteration, not the context or output limit. The launcher does not impose a separate 4096-token output cap; each request's `max_tokens` must fit in the remaining context. The experiment clients retain their own request budgets for comparable measurements.

## Getting Started Instructions

### Prerequisites

- A TACC account with the course `tcloud` command configured in WSL/Linux.
- Permission to request two GPUs, eight CPUs, and one hour on the `tacc` partition.
- A TACC CPU environment that can reach the GPU node's `10.x.x.x` address.
- The course public runtime and shared Qwen weights. No local vLLM build, CUDA installation, or model download is required.
- Bash and Python available through the course environment. The evaluation programs use the standard library and the course `qwen-python` launcher.

### Submit the model server

From your repository copy in a WSL/Linux terminal, register the shared SDK environment once per account, then submit. The setup script can back up and update the account's Conda environment lookup; it does not build vLLM or submit a model job.

```bash
cd /path/to/project/model-server/server-opt
tcloud --help
bash setup-sdk-account.sh
tcloud ps
tcloud submit
```

Record the GPU job ID and inspect its log:

```bash
GPU_ID='<numeric GPU job id>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-public-serve-agent-${GPU_ID}.log"
```

Do not start the evaluation client until the log contains all of the following:

```text
RUNTIME_MODE=public
SERVICE_BASE_URL=http://10.x.x.x:8000/v1
Application startup complete.
AGENT_BASE_URL=http://10.x.x.x:8000/v1
```

The model name is `qwen3.8-27b`. The server exposes the OpenAI-compatible endpoint:

```text
POST ${AGENT_BASE_URL}/chat/completions
```

### Small end-to-end smoke test

Run this from a TACC environment that can reach the GPU node. Replace the URL with the value printed by the ready service log. This uses the same non-streaming response mode as the research Agent:

```bash
BASE_URL='http://10.x.x.x:8000/v1'
curl --noproxy '*' -fsS --connect-timeout 5 --max-time 120 \
  -H 'Content-Type: application/json' \
  "$BASE_URL/chat/completions" \
  --data-binary @- <<'JSON'
{
  "model": "qwen3.8-27b",
  "messages": [{"role": "user", "content": "Reply with exactly: connection_ok"}],
  "stream": false,
  "max_tokens": 32,
  "temperature": 0
}
JSON
```

The expected response is an HTTP 200 JSON object with these fields; the model's exact formatting and timing values can vary:

```text
choices[0].message.content = connection_ok
usage.prompt_tokens / completion_tokens / total_tokens
metrics.telemetry.schema = qwen-agent-telemetry-v1
```

The same endpoint accepts OpenAI-compatible `tools` and returns structured `tool_calls`. The Agent owns tool schemas and function execution; the model server only performs inference and returns the tool call. This small check verifies a model response; it does not run a full research or tool-execution workflow. The evaluation clients below use streaming to measure request timing.

Native per-request timing remains under `response["metrics"]`, including `time_to_first_token_ms`, `mean_itl_ms`, and `tokens_per_second` when provided by vLLM. Additional request/cache counters and GPU snapshots are under `metrics.telemetry`. Streaming responses attach metrics to the final usage SSE event. Preserve this custom field when using an OpenAI client; missing values remain unavailable. GPU readings are completion-time shared-device snapshots, not request averages or peaks. The [backend metrics contract](../../backend/README.md#任务指标与前端接入) describes task aggregation. The optional runtime JSONL copy is `model-server-results/agent-service-<GPU_ID>/requests.jsonl`; clients normally read the response directly.

After testing, stop only the GPU job submitted for this server:

```bash
tcloud cancel -j "$GPU_ID"
```

## Step-by-Step Experiment Procedures

The five experiments use a separate GPU service job and a separate CPU client job. The service must be ready before the client is submitted, and the service is cancelled only after the client results and logs have been downloaded. Do not start a client automatically from `job.sh`.

The commands below assume a WSL shell. Replace `/path/to/project` with the project root and replace every placeholder job ID with the ID printed by your own `tcloud` command.

### Common preparation

Run this once per TACC account:

```bash
PROJECT=/path/to/project/model-server
SERVER_DIR="$PROJECT/server-opt"
cd "$SERVER_DIR"
bash setup-sdk-account.sh
```

The public runtime does not require a build. The service package uses the course public vLLM environment and shared weights. Every public service run must use:

```text
max_model_len=36864
max_num_seqs=4
gpu_memory_utilization=0.9
enable_prefix_caching=true
```

Only the experiment variable is changed. Keep the workload, model, TP=2, dtype, tool parser, and quality rule unchanged.

For every service submission:

```bash
cd "$SERVER_DIR"
tcloud submit
GPU_ID='<GPU service job id>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-public-serve-agent-${GPU_ID}.log"
```

Continue only after the log contains `RUNTIME_MODE=public`, the actual `SERVICE_BASE_URL`, and `Application startup complete.` Record the URL printed by the log as `BASE_URL=http://...:8000/v1`.

### Experiment A: Serial E00 and Prefill-Budget Experiment

**Goal.** Measure the effect of `max_num_batched_tokens` on a single in-flight request. This is the serial `serial-long-copy-screen-v1` quick protocol: three unmeasured warmups and two trials of four cases, for eight measured requests. Test 2048, 4096, and 8192 separately.

**Change only:** `max_num_batched_tokens`. Keep context 36864, sequence limit 4, GPU utilization 0.9, APC enabled, no speculative decoding, and the same `evaluation/data/serial-long-copy-boundary-v2.workload.json` family.

For one budget, create a temporary copy so the final `server-opt` directory is not changed:

```bash
PROJECT=/path/to/project/model-server
BUDGET=2048
RUN_DIR="$PROJECT/server-opt-prefill-$BUDGET"
cp -a "$PROJECT/server-opt" "$RUN_DIR"
for CONFIG in "$RUN_DIR/service_config.json" \
              "$RUN_DIR/evaluation/serial/service_config.json"; do
  python3 -c 'import json,sys; p=sys.argv[1]; b=int(sys.argv[2]); c=json.load(open(p)); c["max_num_batched_tokens"]=b; json.dump(c,open(p,"w"),indent=2); open(p,"a").write("\n")' "$CONFIG" "$BUDGET"
done
```

Submit the temporary server copy:

```bash
cd "$RUN_DIR"
tcloud submit
GPU_ID='<GPU service job id>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-public-serve-agent-${GPU_ID}.log"
BASE_URL='<SERVICE_BASE_URL from the ready log>'
```

Submit the independent serial client:

```bash
cd "$RUN_DIR/evaluation/serial"
printf '%s\n' "$GPU_ID" > service-job-id.txt
printf '%s\n' "$BASE_URL" > server-url.txt
printf 'quick\n' > measurement-mode.txt
tcloud submit
CLIENT_ID='<CPU client job id>'
tcloud ps -j "$CLIENT_ID"
tcloud cat "slurm_log/qwen-latency-quality-${CLIENT_ID}.log"
```

The client log should contain `PROTOCOL=serial-long-copy-screen-v1`, `WARMUP_COMPLETE=3`, `METRICS_REQUESTS=2`, `RUN_COMPLETE measured_requests=8 PROFILE=quick`, and a passing `QUALITY_GATE`.

Download the evidence before cancelling the service:

```bash
RESULT="$RUN_DIR/results/prefill-$BUDGET-$CLIENT_ID"
mkdir -p "$RESULT"
for name in summary.json answers.jsonl workload.json warmup.json tokenization.json \
            service_config.json server-metrics-before.txt server-metrics-after.txt metrics-boundaries.jsonl; do
  tcloud download "model-server-results/job-$CLIENT_ID/$name" "$RESULT/$name"
done
tcloud download "slurm_log/qwen-latency-quality-${CLIENT_ID}.log" "$RESULT/client.log"
tcloud download "slurm_log/qwen-public-serve-agent-${GPU_ID}.log" "$RESULT/service.log"
tcloud cancel -j "$GPU_ID"
```

Repeat the same procedure for `BUDGET=4096` and `BUDGET=8192`. Use fresh service and client jobs for each budget. Compare `summary.json` fields `elapsed_s`, `ttft_s`, `tpot_s`, token totals, prefill counters, prefix-cache hit rate, and quality. Do not mix these quick results with the 24-request `serial-long-copy-boundary-v2` table.

### Experiment B: Concurrent Baseline

**Goal.** Establish the native vLLM continuous-batching baseline at C=1 and C=4 before changing chunked-prefill or source code. Use `concurrent-long-copy-screen-v1`: two waves of four streaming requests, three unmeasured warmups, and eight measured requests per client job.

For the historical baseline, use `max_num_batched_tokens=4096`. Make a temporary copy and change both the service and concurrency-client configuration:

```bash
PROJECT=/path/to/project/model-server
RUN_DIR="$PROJECT/server-opt-concurrency-baseline-4096"
cp -a "$PROJECT/server-opt" "$RUN_DIR"
for CONFIG in "$RUN_DIR/service_config.json" \
              "$RUN_DIR/evaluation/concurrency/service_config.json"; do
  python3 -c 'import json,sys; p=sys.argv[1]; c=json.load(open(p)); c["max_num_batched_tokens"]=4096; json.dump(c,open(p,"w"),indent=2); open(p,"a").write("\n")' "$CONFIG"
done
```

Deploy the GPU service and wait for readiness:

```bash
cd "$RUN_DIR"
tcloud submit
GPU_ID='<GPU service job id>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-public-serve-agent-${GPU_ID}.log"
BASE_URL='<SERVICE_BASE_URL from the ready log>'
```

Run C=1 first:

```bash
cd "$RUN_DIR/evaluation/concurrency"
printf '%s\n' "$GPU_ID" > service-job-id.txt
printf '%s\n' "$BASE_URL" > server-url.txt
printf '1\n' > concurrency-level.txt
tcloud submit
C1_ID='<C1 client job id>'
tcloud ps -j "$C1_ID"
tcloud cat "slurm_log/qwen-concurrency-quality-${C1_ID}.log"
```

The log should contain `PROTOCOL=concurrent-long-copy-screen-v1`, `CONCURRENCY_LEVEL=1`, `WARMUP_COMPLETE=3`, `RUN_COMPLETE measured_requests=8 PROFILE=concurrency`, and a passing `QUALITY_GATE`.

Keep the same GPU service alive and run C=4:

```bash
printf '4\n' > concurrency-level.txt
tcloud submit
C4_ID='<C4 client job id>'
tcloud ps -j "$C4_ID"
tcloud cat "slurm_log/qwen-concurrency-quality-${C4_ID}.log"
```

Download each client result into a separate directory:

```bash
for CLIENT_ID in "$C1_ID" "$C4_ID"; do
  RESULT="$RUN_DIR/results/job-$CLIENT_ID"
  mkdir -p "$RESULT"
  for name in summary.json answers.jsonl workload.json warmup.json tokenization.json \
              service_config.json server-metrics-before.txt server-metrics-after.txt metrics-boundaries.jsonl; do
    tcloud download "model-server-results/job-$CLIENT_ID/$name" "$RESULT/$name"
  done
  tcloud download "slurm_log/qwen-concurrency-quality-$CLIENT_ID.log" "$RESULT/client.log"
done
tcloud download "slurm_log/qwen-public-serve-agent-${GPU_ID}.log" "$RUN_DIR/results/service-$GPU_ID.log"
tcloud cancel -j "$GPU_ID"
```

Compare C=1 and C=4 separately. C=1 is not a candidate implementation; it is the single-in-flight reference. Report E2E, TTFT, TPOT, requests/s, output tokens/s, queue time, prefix-cache hit rate, prefill counters, and quality.

### Experiment C: C=4 Chunked-Prefill Experiment

**Goal.** Test whether the scheduler budget changes the C=4 tradeoff between first-token latency and decode throughput. Run only C=4, with separate GPU services for 2048, 4096, and 8192.

For each `BUDGET` in `2048 4096 8192`:

```bash
PROJECT=/path/to/project/model-server
BUDGET=8192
RUN_DIR="$PROJECT/server-opt-chunk-$BUDGET"
cp -a "$PROJECT/server-opt" "$RUN_DIR"
for CONFIG in "$RUN_DIR/service_config.json" \
              "$RUN_DIR/evaluation/concurrency/service_config.json"; do
  python3 -c 'import json,sys; p=sys.argv[1]; b=int(sys.argv[2]); c=json.load(open(p)); c["max_num_batched_tokens"]=b; json.dump(c,open(p,"w"),indent=2); open(p,"a").write("\n")' "$CONFIG" "$BUDGET"
done
cd "$RUN_DIR"
tcloud submit
GPU_ID='<GPU service job id>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-public-serve-agent-${GPU_ID}.log"
BASE_URL='<SERVICE_BASE_URL from the ready log>'
cd "$RUN_DIR/evaluation/concurrency"
printf '%s\n' "$GPU_ID" > service-job-id.txt
printf '%s\n' "$BASE_URL" > server-url.txt
printf '4\n' > concurrency-level.txt
tcloud submit
CLIENT_ID='<C4 client job id>'
tcloud ps -j "$CLIENT_ID"
tcloud cat "slurm_log/qwen-concurrency-quality-${CLIENT_ID}.log"
```

For each budget, save `summary.json`, `answers.jsonl`, `workload.json`, `tokenization.json`, both metrics boundary files, the client log, and the service log. Verify that all three runs have the same workload hash and 8/8 quality before comparing them. The main comparison fields are E2E, TTFT, TPOT, requests/s, output tokens/s, queue time, prefill time, computed-prefill tokens, prefix-cache hit rate, and preemptions.

The expected recorded trend was: 2048 had the worst C=4 throughput; 8192 reduced TPOT and slightly increased requests/s relative to 4096, but increased TTFT. Keep 8192 as the final throughput-oriented setting only after documenting this tradeoff.

### Experiment D: GDN Indexed-State Experiment

**Important scope.** GDN changes the private vLLM source. The public `server-opt` service cannot reproduce this candidate by itself. Run this experiment from the complete `qwen27b-private-vllm-latency_old` tree, where the private source, build scripts, variant manifests, and the reviewed candidate files are present. The archived helper is in `experiments/gdn_experiment.py`; the complete procedure is documented in this README.

1. Select the candidate and build the private runtime:

```bash
PRIVATE=/path/to/project/qwen27b-private-vllm-latency_old
cd "$PRIVATE"
.venv-linux/bin/python gdn_experiment.py select candidate
bash submit-build.sh
BUILD_ID='<private build job id>'
tcloud ps -j "$BUILD_ID"
tcloud cat "slurm_log/qwen-latency-build-${BUILD_ID}.log"
```

Wait for `PRIVATE VLLM BUILD PASSED`. Do not deploy the candidate after a failed build.

2. Submit the independent private GPU service:

```bash
cd "$PRIVATE/qwen-private-serve"
tcloud submit
GPU_ID='<private candidate GPU job id>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-latency-serve-${GPU_ID}.log"
```

Before sending a client request, verify `RUNTIME_MODE=private`, `PRIVATE VLLM / PUBLIC DEPENDENCIES CHECK PASSED`, the candidate `PRIVATE_SOURCE_VARIANT`, `GDN_KERNEL_CHECK_PASSED=2`, the expected 36864/4096/seq4/0.9/APC/TP2/BF16 settings, and `Application startup complete.` The kernel check is a real two-GPU small-tensor check; it is not a full-model performance result.

3. Submit the independent 24-request serial client:

```bash
cd "$PRIVATE/qwen-private-serial-cache"
printf '%s\n' "$GPU_ID" > service-job-id.txt
printf '%s\n' '<SERVICE_BASE_URL from the GPU log>' > server-url.txt
printf 'long\n' > measurement-mode.txt
tcloud submit
CLIENT_ID='<private candidate CPU job id>'
tcloud ps -j "$CLIENT_ID"
tcloud cat "slurm_log/qwen-latency-quality-${CLIENT_ID}.log"
```

The client should show `PROTOCOL=serial-long-copy-boundary-v2`, `RUN_COMPLETE measured_requests=24`, `METRICS_REQUESTS=2`, and a passing quality gate. The service log should show the GDN indexed-state path.

4. Save and compare the candidate:

```bash
cd "$PRIVATE"
RESULT="results/job-$CLIENT_ID"
mkdir -p "$RESULT"
for name in summary.json answers.jsonl workload.json warmup.json service_config.json \
            server-metrics-before.txt server-metrics-after.txt metrics-boundaries.jsonl; do
  tcloud download "model-server-results/job-$CLIENT_ID/$name" "$RESULT/$name"
done
tcloud download "slurm_log/qwen-latency-quality-${CLIENT_ID}.log" "$RESULT/client.log"
tcloud cancel -j "$GPU_ID"
tcloud download "slurm_log/qwen-latency-serve-${GPU_ID}.log" "$RESULT/service.log"
.venv-linux/bin/python gdn_experiment.py compare results/job-30056 "$RESULT"
```

Compare only after checking 24/24 quality, no truncation, identical protocol and metric-code hashes, and the candidate kernel evidence. The recorded candidate was slower, so the experiment is a negative optimization result.

### Experiment E: GPU N-gram Speculative-Decoding Experiment

**Important scope.** GPU N-gram also requires the private vLLM runtime. It is an existing vLLM feature configuration, not a new decoding algorithm in this project. Restore the original private baseline source before enabling it; do not stack it on top of the GDN candidate. The archived helper is in `experiments/speculative_experiment.py`; the complete procedure is documented in this README.

1. Select the N-gram candidate and build the restored private baseline if the installed runtime is not already matched:

```bash
PRIVATE=/path/to/project/qwen27b-private-vllm-latency_old
cd "$PRIVATE"
.venv-linux/bin/python speculative_experiment.py select candidate
bash submit-build.sh
BUILD_ID='<private build job id>'
tcloud ps -j "$BUILD_ID"
tcloud cat "slurm_log/qwen-latency-build-${BUILD_ID}.log"
```

Wait for `PRIVATE VLLM BUILD PASSED`. The candidate configuration is:

```text
method=ngram_gpu
num_speculative_tokens=3
prompt_lookup_min=2
prompt_lookup_max=5
async_scheduling=true
```

2. Submit the private service:

```bash
cd "$PRIVATE/qwen-private-serve"
tcloud submit
GPU_ID='<N-gram GPU job id>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-latency-serve-${GPU_ID}.log"
```

The log must show the original private baseline source, `SPECULATIVE_CONFIG_REQUESTED` with `ngram_gpu`, `ASYNC_SCHEDULING_REQUESTED=true`, the speculative engine configuration, and `Application startup complete.` If CUDA graph capture fails with a Triton stream-capture error, preserve the log and stop; there is no valid performance result.

3. Download the ready log, bind it, and submit the separate long client:

```bash
cd "$PRIVATE"
mkdir -p results
tcloud download "slurm_log/qwen-latency-serve-${GPU_ID}.log" "results/service-${GPU_ID}-ngram-gpu.log"
.venv-linux/bin/python speculative_experiment.py bind candidate \
  --service-job-id "$GPU_ID" \
  --service-log "results/service-${GPU_ID}-ngram-gpu.log"
cd qwen-private-serial-cache
tcloud submit
CLIENT_ID='<N-gram CPU job id>'
tcloud ps -j "$CLIENT_ID"
tcloud cat "slurm_log/qwen-latency-quality-${CLIENT_ID}.log"
```

The client should show 24 measured requests, `METRICS_REQUESTS=2`, and a passing quality gate. Save the full result, cancel the service, then compare against the fixed public baseline:

```bash
cd "$PRIVATE"
RESULT="results/job-$CLIENT_ID"
mkdir -p "$RESULT"
for name in summary.json answers.jsonl workload.json warmup.json service_config.json \
            server-metrics-before.txt server-metrics-after.txt metrics-boundaries.jsonl; do
  tcloud download "model-server-results/job-$CLIENT_ID/$name" "$RESULT/$name"
done
tcloud download "slurm_log/qwen-latency-quality-${CLIENT_ID}.log" "$RESULT/client.log"
tcloud cancel -j "$GPU_ID"
tcloud download "slurm_log/qwen-latency-serve-${GPU_ID}.log" "$RESULT/service.log"
.venv-linux/bin/python speculative_experiment.py compare results/job-30056 "$RESULT"
```

Report draft-token count, accepted-token count, acceptance rate, E2E, TTFT, TPOT, output-token totals, quality, and whether the speculative counter window is known to cover all 24 requests. Missing counters are unknown, not zero. The recorded GPU N-gram result was slower and is not a final setting.

## Detailed Instructions

### Package layout

```text
server-opt/
|-- job.sh, main.py, tuxiv.conf
|-- service_config.json, runtime-mode.txt
|-- patch_serve.py, agent_telemetry.py
|-- check-public-env.py, check.py, service_supervisor.py
|-- source-reference.json, BASE_URL_HANDOFF.txt, setup-sdk-account.sh
|-- evaluation/
|   |-- concurrency/       # C=1/C=4 and chunked-prefill client
|   |-- serial/            # full serial and quick screening client
|   +-- data/              # frozen workload/tokenization snapshots
|-- experiments/           # archived experiment helpers and original procedures
|   +-- configs/          # per-experiment service configuration snapshots
|-- results/               # selected machine-readable result summaries
+-- reports/               # English model-server report
```

Configuration snapshots for every reported budget and candidate are in `experiments/configs/`: serial prefill 2048/4096/8192, C=4 budgets 2048/4096/8192, GDN serial/C4 candidates, and GPU N-gram. Copy the matching snapshot into both the service and client configuration locations before submitting a run; do not edit the final `server-opt/service_config.json` in place.

The workload is deterministic code, not an external download. `long_workload.py` generates the synthetic 72-record and 216-record document families; `quick_workload.py` selects the four quick-screen cases. The `evaluation/data/` directory also contains frozen workload and tokenizer snapshots from the recorded baseline, so the expected input shape and token counts can be inspected before submission. The evaluation clients save a copy of the generated workload and its SHA-256 hash in each result directory.

The TACC environment is activated inside each job with the course public activation script. The job does not build vLLM or download weights. The service supervisor is the unchanged teaching-assistant supervisor from `cinecontext-qwen-e2e-fix.zip`.

### Re-run the C=4 optimized evaluation

1. Submit `server-opt` as described in Getting Started and wait for readiness.
2. Put the current service job ID and URL into the concurrency client configuration:

```bash
cd /path/to/project/model-server/server-opt/evaluation/concurrency
printf '%s\n' "$GPU_ID" > service-job-id.txt
printf '%s\n' "$BASE_URL" > server-url.txt
printf '4\n' > concurrency-level.txt
tcloud submit
```

3. The client job runs `concurrency_quality.py --concurrency 4`. It performs token-budget validation, three warmups, one `/metrics` snapshot before timing, eight streaming requests, one `/metrics` snapshot after timing, exact quality checks, and writes results under `model-server-results/job-<CLIENT_ID>/`.
4. Save the client and server evidence:

```bash
CLIENT_ID='<numeric client job id>'
mkdir -p "results/job-$CLIENT_ID"
tcloud download "model-server-results/job-$CLIENT_ID/summary.json" \
  "results/job-$CLIENT_ID/summary.json"
tcloud download "model-server-results/job-$CLIENT_ID/answers.jsonl" \
  "results/job-$CLIENT_ID/answers.jsonl"
tcloud download "model-server-results/job-$CLIENT_ID/workload.json" \
  "results/job-$CLIENT_ID/workload.json"
tcloud download "slurm_log/qwen-concurrency-quality-$CLIENT_ID.log" \
  "results/job-$CLIENT_ID/client.log"
tcloud download "slurm_log/qwen-public-serve-agent-$GPU_ID.log" \
  "results/job-$CLIENT_ID/service.log"
```

5. Check `quality_passed=true`, `measured_requests=8`, the workload hash, and the actual vLLM arguments in the service log. Cancel the GPU service only after all files are downloaded.

### Re-run C=1

Use the same service configuration and workload, but change only the client concurrency:

```bash
cd /path/to/project/model-server/server-opt/evaluation/concurrency
printf '1\n' > concurrency-level.txt
tcloud submit
```

C=1 and C=4 must be reported separately. They are different load levels, not baseline and candidate implementations.

### Re-run the chunked-prefill comparison

Follow **Experiment C** for budgets 2048, 4096, and 8192. Its commands create a separate copy for each budget and update both the GPU service configuration and the configuration recorded by the CPU client. Use a fresh service/client job pair for each budget, with the same workload hash and quality rule. Keep results separate and leave the final `server-opt` configuration unchanged.

### Re-run the serial control

The serial client is in `evaluation/serial`. Set:

```bash
cd /path/to/project/model-server/server-opt/evaluation/serial
printf '%s\n' "$GPU_ID" > service-job-id.txt
printf '%s\n' "$BASE_URL" > server-url.txt
printf 'quick\n' > measurement-mode.txt
tcloud submit
```

For the complete 24-request protocol, use `long` instead of `quick` in `measurement-mode.txt`. The full protocol is the formal serial control; the quick protocol is for screening only and must not be mixed into the full-v2 table.

### Metrics and result interpretation

Report the following for every valid run:

- TTFT, TPOT, and end-to-end latency;
- requests/s and output tokens/s;
- input, output, and total tokens;
- prefix-cache query tokens, hit tokens, and hit rate;
- computed prefill tokens and prefill time;
- queue time and preemption count;
- quality pass count and request errors.

The service reads `/metrics` only at the experiment boundaries. GPU memory, GPU utilization, KV-cache utilization, and running/waiting request counts require a working sidecar sampler. The final recorded sampler files were empty, so these values must be reported as unavailable rather than inferred.

### Reproduction artifacts and report references

The selected result summaries are in [`results/`](results/). The English report is [`reports/Server_report.md`](reports/Server_report.md). Its corresponding sections are:

- §3.1: serial prefill-budget screening at 2048/4096/8192;
- §3.2: C=1/C=4 concurrent baseline;
- §3.3: C=4 chunked-prefill budgets 2048/4096/8192;
- §3.4: GDN indexed-state comparison;
- §3.5: GPU N-gram speculative-decoding result.

The JSON files retain job IDs, workload hashes, token totals, quality gates, latency summaries, engine counters, and caveats. They are reference evidence, not new measurements from this package.

## Known limitations

- Keep `runtime-mode.txt` set to `public`. The private build tree, GDN candidate source and private-runtime checks referenced by Experiments D/E are not included; the archived experiment helpers and summaries alone cannot reproduce those private-runtime results.
- TACC can place runs on different GPU nodes; small changes in latency cannot automatically be attributed to the configuration.
- The quick concurrent screen has eight measured requests and does not replace the full Agent workload.
- The 8192 versus 4096 end-to-end difference was below one percent and is directional because nodes were not perfectly matched.
- Resource sampling was unavailable for the final runs; no GPU memory, utilization, or KV-cache peak claim is made.
- Startup and CUDA-graph compilation are outside request timing, but inference-time Triton JIT warnings can influence early requests.
- The service must stay alive while the independent client job runs. `check.py` only keeps the deployment alive; it does not generate evaluation traffic.
