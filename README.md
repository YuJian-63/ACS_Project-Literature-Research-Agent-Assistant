# Literature Research Agent Assistant

[Chinese version](READMD_zh.md)

A course project for HKUST CSIT6000V, Advanced AI Computing and Systems. Users can upload PDFs, search arXiv, import papers, and submit research questions. Baseline and Retrieval Extension workflows run locally or on TACC using the Bailian API or a separately deployed Qwen service.

## Getting Started Instructions

**Public deployment:** [https://8.218.149.237/](https://8.218.149.237/). Open this address to register, verify your email, and sign in to the deployed service. The following instructions cover local setup and self-hosting.

### 1. Prerequisites

| Component | Requirements |
| --- | --- |
| Operating system | Windows PowerShell, Linux, or macOS. Run commands from the repository root unless stated otherwise. |
| Development tools | Git, uv, and Python 3.12. The backend requires Python >= 3.11; the standalone Agent requires Python 3.12. |
| Frontend | Node.js 22.12 or later and npm; see [package.json](frontend/package.json) for the complete supported version range. |
| Database | Running Docker with the Compose plugin. The scripts use PostgreSQL 17; an existing PostgreSQL instance is also supported. |
| Email | An SMTP mailbox and authorization code supporting SSL/TLS on port 465 for registration verification. The examples use QQ Mail. |
| Research model | A Bailian API key, the compatible endpoint for its workspace, and an available model ID. The web research example below calls Bailian from a TACC CPU job and requires no GPU allocation. |
| Evaluation model | DeepSeek Flash for task scoring; configure its endpoint, model ID, and credentials. |
| TACC / TCloud | A valid course account, the private key corresponding to a registered public key, an initialized `tcloud` SDK, and an SDK-compatible Python 3.12 environment. The cluster is unnecessary for starting the web interface, registering, or uploading PDFs. |
| Network and ports | Access to dependency and image downloads, SMTP, and TACC. Both the Worker and compute nodes must reach Bailian; compute nodes must reach the paper library over HTTPS. Local ports `5173`, `8000`, and the default database port `55432` must be available; the temporary library endpoint also uses `8001`. |

Initial installation requires internet access, and real research incurs model API charges. Supply your own credentials and keep private `.env` files out of Git.

### 2. Get the Code and Initialize

```sh
git clone https://github.com/YuJian-63/ACS_Project-Literature-Research-Agent-Assistant.git
cd ACS_Project-Literature-Research-Agent-Assistant
git rev-parse HEAD
```

Record the commit SHA to identify the version used. Skip cloning if you already have a working copy. Choose the initialization command for your operating system:

| System | Command |
| --- | --- |
| Windows PowerShell | `.\scripts\service-windows.ps1 init` |
| Linux | `bash scripts/service-linux.sh init` |
| macOS | `bash scripts/service-macos.sh init` |

Initialization installs backend and frontend dependencies, creates `backend/.env` if missing, generates any missing values for three independent security keys, starts the database, and applies migrations. On first setup, research dispatch, arXiv, and evaluation are disabled. Existing nonempty settings and keys are preserved. Successful initialization prints:

```text
Initialization complete. Run start to launch the services.
```

If Windows blocks script execution, run `powershell -ExecutionPolicy Bypass -File .\scripts\service-windows.ps1 init`; replace `init` with `start` when launching services. To use an existing PostgreSQL instance, configure `DATABASE_URL` in `backend/.env` first, then add `--external-db` to **both init and start**, or `-ExternalDb` on Windows.

### 3. Configure Registration Email and TCloud Research

Using the same operating-system account that runs the backend Workers, configure your course account and private key following the [TCloud initialization instructions](tacc/README.md#常用-tcloud-命令), then run `tcloud init` and `tcloud env ls`. Confirm that the SDK can use a Python 3.12 environment. The examples use `acs-network-probe`, which the local initialization scripts do not create. Cluster directory permissions and SDK path requirements must also be satisfied.

Edit the generated private `backend/.env` and update these fields, preserving the generated `AUTH_RATE_KEY`, `AUTH_CSRF_KEY`, and `MAIL_OUTBOX_KEY`:

```dotenv
FRONTEND_PUBLIC_URL=http://127.0.0.1:5173
CORS_ORIGINS=["http://127.0.0.1:5173"]
AUTH_COOKIE_SECURE=false

SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USERNAME=your-mailbox@qq.com
SMTP_FROM=your-mailbox@qq.com
SMTP_AUTH_CODE=replace-with-your-smtp-authorization-code

TASK_RUNNER=agent
AGENT_DISPATCH_ENABLED=true
AGENT_TRANSPORT=tcloud
AGENT_TCLOUD_CLI=tcloud
AGENT_TCLOUD_ENV_NAME=acs-network-probe
AGENT_TCLOUD_MODEL_ENV_FILE=../agent/.env
AGENT_LIBRARY_PUBLIC_URL=https://your-library-host.example
AGENT_PERSIST=false
ARXIV_ENABLED=false
EVALUATION_ENABLED=false
```

`SMTP_USERNAME` and `SMTP_FROM` must match; `SMTP_AUTH_CODE` is the SMTP authorization code. Replace the environment name with your own usable environment. Set the library HTTPS origin in the next step; do not leave the example domain or use `127.0.0.1`, which the cluster cannot reach.

Copy [agent/.env.example](agent/.env.example) to `agent/.env` on first setup, or edit the existing file. Set the following in this private file:

```dotenv
MODEL_PROVIDER=bailian
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen3.8-27b
BAILIAN_API_KEY=replace-with-your-bailian-api-key
```

Use an endpoint and model ID available to your account; do not enter an API key in the endpoint field. On Linux/macOS, run `chmod 600 agent/.env` and ensure that the Worker account owns the file. The Worker reads it to request a temporary Bailian key for each job. This execution path prepares Agent dependencies within the job, so no local Agent virtual environment is required. The example uses Baseline and an uploaded paper, requiring neither Tavily nor embeddings nor a separate Agent persistence database.

The frontend uses the same-origin API by default, so `frontend/.env.local` is unnecessary. If you already have frontend configuration, verify that its proxy still points to `127.0.0.1:8000`. See [backend configuration](backend/README.md#配置与账号) and [Agent configuration](agent/README.md) for additional fields.

### 4. Expose the Paper Library to Compute Nodes

If you already have a public HTTPS endpoint that proxies this backend library API, set its origin as `AGENT_LIBRARY_PUBLIC_URL` and skip the remaining commands in this section. For local development without a public endpoint, install `cloudflared`, open another terminal, and start the read-only library API from the repository root:

```sh
cd backend
uv run --locked uvicorn app.main:create_library_app --factory --host 127.0.0.1 --port 8001
```

Open another terminal to establish a temporary HTTPS tunnel:

```sh
cloudflared tunnel --url http://127.0.0.1:8001
```

Set `AGENT_LIBRARY_PUBLIC_URL` in `backend/.env` to the printed `https://...trycloudflare.com` origin, without an API path. Keep both terminals running. The library API must share the main API's database, storage, and authentication keys. Recreating the tunnel may change its address; update the configuration and restart the research Runner if it does. The platform-specific `service-* start` commands do not launch the library endpoint or tunnel automatically. In Bash environments, the [TACC launch workflow](tacc/TACC.md#本机一键启动) can manage them together.

### 5. Start and Check the Services

| System | Command |
| --- | --- |
| Windows PowerShell | `.\scripts\service-windows.ps1 start` |
| Linux | `bash scripts/service-linux.sh start` |
| macOS | `bash scripts/service-macos.sh start` |

Keep the terminal running. With the configuration above, the launcher starts the API, Parser, Mail, Agent Runner, and Vite. Its output should include:

```text
Workers: parser, mail, runner
Open http://127.0.0.1:5173 . Ctrl+C stops this launcher's services; PostgreSQL is kept.
```

Check the API from another terminal; use `curl.exe` instead of `curl` on Windows:

```sh
curl --noproxy '*' -fsS http://127.0.0.1:8000/health
curl --noproxy '*' -fsS http://127.0.0.1:8000/ready
```

The requests should return `{"status":"ok"}` and `{"status":"ready"}`, respectively. These endpoints check liveness, the database, and migrations. The following example also verifies registration email, research execution, and citations.

### 6. Minimal End-to-End Example

Use the included two-page synthetic paper, [Orchid Calibration Report.pdf](<frontend/checks/fixtures/Orchid Calibration Report.pdf>); no external paper download is needed:

1. Open `http://127.0.0.1:5173`, register, verify your email, and sign in. Usernames must contain 3-32 English letters, digits, or underscores; system-reserved names such as `Admin` are unavailable. Preserve the registered letter case when signing in.
2. Upload the PDF to the paper library, wait until its status is `ready`, and confirm that the original PDF opens.
3. Create a research task and select this paper. Choose **Bailian API** as the model source and **Baseline** as the research mode, disable additional search, and submit the following question:

   ```text
   Search only my paper library. What is the checksum tag in the final calibration record of "Orchid Calibration Report"? Cite the original text on page 2.
   ```

4. Wait for completion in the research records, open the answer, and click a citation to verify the evidence and PDF page number.

**Expected result:** The paper has status `ready` and 2 pages. The research task finishes with status `succeeded`, the answer includes `LUMEN-472`, and its citation opens page 2 of the PDF. In the signed-in browser's developer tools, `POST /api/v1/agent-research` returns `202`; a subsequent `GET /api/v1/agent-research/{task_id}` contains `status: "succeeded"` and a nonempty `result`. Task UUIDs, wording, and elapsed time vary; an exact text match is unnecessary.

If a task stays queued, check the Runner and `tcloud ps`. If an upload does not become `ready`, check the Parser. If verification email does not arrive, check Mail and the spam folder. Logs are `api.log`, `parser.log`, `mail.log`, and `runner.log` under `backend/runtime/services/`. To verify only account and PDF functionality, set `AGENT_DISPATCH_ENABLED=false` and skip the cluster, model, and tunnel setup; the research example cannot complete in that configuration. See [service startup and integration](docs/service_launch.md).

### 7. Optional: Start the DeepSeek Evaluation Worker

To score research results, configure a separate evaluation model in the private `backend/.env`:

```dotenv
EVALUATION_ENABLED=true
EVALUATION_BASE_URL=https://api.deepseek.com
EVALUATION_MODEL=replace-with-an-available-deepseek-model-id
EVALUATION_API_KEY=replace-with-your-deepseek-api-key
```

Evaluation credentials are independent of the Agent research model configuration. When using the launch scripts above, press Ctrl+C to stop the current services, then rerun the `start` command for your operating system. The API and research Worker reload configuration, and the evaluation Worker starts automatically. With the other quick-start settings unchanged, the output should include `Workers: parser, mail, runner, evaluation`. Evaluation logs are written to `backend/runtime/services/evaluation.log`.

Once enabled, evaluation automatically scores newly delivered research results; it does not scan historical tasks. Request evaluation explicitly for older results. Evaluation failures do not overwrite the research answer. Evaluation status and the five scoring dimensions are available from the task detail API.

If managing processes manually, restart the API and research Worker after changing configuration, then run this in another terminal:

```sh
cd backend
uv run --locked python -m app.evaluation_worker
```

Do not also start this command manually if the launcher already manages the evaluation Worker. ECS uses a separate `acs-evaluation.service`; see [backend evaluation services](backend/README.md#deepseek-evaluation) for installation and service management.

## Detailed Instructions

### Project Structure and Data Flow

The browser manages papers and tasks through the API. The backend passes inputs to the standalone Agent and stores its answers, citations, and metrics. PostgreSQL stores application data, while backend file storage holds original PDFs. Model credentials stay outside the browser.

| Directory | Responsibility |
| --- | --- |
| [frontend/](frontend/README.md) | React / TypeScript research workspace with accounts, a paper library, task details, and original evidence views. |
| [backend/](backend/README.md) | FastAPI, PostgreSQL, migrations, and background Workers for parsing, email, research, and related services. |
| [agent/](agent/README.md) | Baseline and Retrieval Extension workflows for reading papers, retrieving passages, and citing evidence. Includes instructions for running the Agent ablation. |
| [tacc/](tacc/README.md) | Course SDK, environment configuration, and probe scripts. [run_job.py](tacc/research/run_job.py) reads task manifests and invokes the Agent. |
| [model-server/](model-server/README.md) | Original TACC Qwen service, [optimized service](model-server/server-opt/README.md), telemetry, and model-serving experiments. |
| [scripts/](docs/service_launch.md#按系统使用脚本) | Platform-specific local launchers, TACC integration, and ECS service entry points. |
| [ops/deploy/](ops/deploy/) | ECS release scripts and checks. The [deployment workflow](.github/workflows/deploy-ecs.yml) runs on pushes to `main`. |
| [docs/](docs/) | [API contract](docs/api-contract.md), [database design](docs/database-design.md), [service startup](docs/service_launch.md), and [proposal](docs/Proposal.md). |

### Other Execution Modes

- **Manual startup / external database:** See [service startup](docs/service_launch.md). The launcher's `check` command checks configuration and tools only; it does not verify model, email, or cluster connectivity.
- **Standalone local Agent:** Run the CLI following the [Agent documentation](agent/README.md). Web `local` dispatch requires a compatible `run_dispatch.py` entry point, which the current `agent/` directory does not provide. Switching only `AGENT_TRANSPORT=local` cannot replace the TCloud path above.
- **TACC / TCloud:** Requires a course account, a registered SSH public key, an initialized SDK, a usable execution environment, and a library HTTPS origin reachable from compute nodes. Follow [initial setup](tacc/TACC.md#首次配置从新账号注册到网页研究). Local commands include `./scripts/local-research configure` and `./scripts/research up`; without a fixed public endpoint, follow the [tunnel workflow](tacc/TACC.md#本机一键启动).
- **TACC model:** Launch the GPU service following the [model-server instructions](model-server/README.md). Web model management still submits the original `server/` service. For the [optimized `server-opt/` service](model-server/server-opt/README.md), submit a GPU job manually and select the custom service address option when creating research. Agent jobs must be able to reach that address; cluster-private addresses may be unreachable directly from ECS or a personal computer. Manage the model service and Agent CPU jobs separately.
- **Deployed ECS:** Use the installed systemd services, Nginx, and HTTPS. Run `./scripts/research up` under an authorized account, set a compute-node-accessible `AGENT_LIBRARY_PUBLIC_URL`, and update code through the automatic deployment workflow. Local development scripts do not install these production components.

### Configuration, Data, and Operational Limits

- Configuration examples are `backend/.env.example`, `agent/.env.example`, and `frontend/.env.example`. The API and backend Workers share the database, storage, and account security keys. Environment variables take precedence over `.env`. `VITE_*` values are included in the browser bundle and must contain only public configuration.
- Web arXiv search/import requires `ARXIV_ENABLED`, a contact email, and the Import Worker. Agent external search additionally requires Tavily. See the [Agent documentation](agent/README.md) for Retrieval Extension embeddings and optional switches.
- The backend task detail API exposes five-dimensional DeepSeek evaluation, Agent calls and token counts, and model-server performance and cache metrics. See the [task metrics contract](backend/README.md#任务指标与前端接入) for fields and access. Metrics absent from model-server responses are marked unavailable. GPU metrics are sampled snapshots and must not be treated as task-average utilization.
- Each uploaded/imported PDF is limited to 50 MB, with at most 20 initially selected papers. Public reverse proxies must also allow multipart overhead. See [dispatch and budgets](backend/README.md#agent-dispatch) for step limits, timeouts, output tokens, and user quotas. Model management can set site-wide research concurrency to 1-4, shared by all accounts.
- PDFs, database volumes, and logs are not transferred by cloning Git. Ctrl+C stops the local services started by the current launcher and preserves the database. To stop the database, run `docker compose stop postgres` from `backend/`. Back up existing data before reinitialization or migration. Editing `.env` does not reset credentials in an existing database volume.
- The example verifies a small functional workflow. Text extraction, context length, model output, and network conditions affect real-paper answers and citations; scanned PDFs may lack usable text. TACC execution time also depends on queueing and resources. Users must supply model and SMTP credentials.

### Evaluation

The project evaluation consists of three experiments. This section documents test cases, data, configurations, commands, and metric definitions. Numerical results belong in the corresponding reports and result files. Run the Bash commands on Linux, macOS, or Windows WSL, starting from the repository root unless stated otherwise.

| Experiment | Research question | Cases and configurations | Reports or outputs |
| --- | --- | --- | --- |
| [1. Agent ablation](#evaluation-agent) | What changes do RAG, Planner, and Reflection introduce individually? | 5 case types x 5 component configurations, totaling 25 runs. | Per-run `result.json` and `trace.json`. Results are in §7.1.1 of the [final report](Report.pdf). |
| [2. Model Server](#evaluation-model-server) | How do concurrency, scheduling budgets, and candidate optimizations affect inference? | Serial / C=1 / C=4; prefill budgets 2048 / 4096 / 8192; archived GDN and N-gram candidates. | [Model-server report](model-server/server-opt/reports/Server_report.md) and [result summaries](model-server/server-opt/results/). |
| [3. End-to-end research](#evaluation-end-to-end) | How do quality, cost, and waiting time change for user research tasks? | Four research task types, 15 Baseline / Extension pairs, and archived unpaired runs. | [End-to-end report](Report.pdf) and [frozen manifest](docs/evaluation/researcher-20261123.json). |

Agent ablation compares component switches, the Model Server experiment compares inference services, and the end-to-end experiment compares the full user-visible research workflow. Their model providers, workloads, and timing boundaries differ; do not pool their data into a single comparison.

<a id="evaluation-agent"></a>

#### 1. Agent Ablation Experiment

##### Test Cases and Component Configurations

| Case | Data and task | Paper library requirements |
| --- | --- | --- |
| `library-qa` | [`library-qa.json`](agent/examples/library-qa.json): find SkillOpt and explain what it optimizes and how it decides whether to retain an update. | Upload/import SkillOpt under your account, verify that title search finds it, and record the paper version and PDF SHA-256. |
| `qa` | [`qa.json`](agent/examples/qa.json): explain the `sqrt(d_k)` scaling in scaled dot-product attention using *Attention Is All You Need*. | None; `1706.03762v7` is preselected. |
| `summary` | [`summary.json`](agent/examples/summary.json): summarize the same paper's problem, method, translation results, and applicability. | None; `1706.03762v7` is preselected. |
| `review` | [`review.json`](agent/examples/review.json): find LoRA / QLoRA and compare their methods and GPU-memory savings. | None; external search is required. |
| `discovery` | [`discovery.json`](agent/examples/discovery.json): survey Agents that update existing skills using experience. | Sign in to the paper library and keep its visible contents identical across configurations. |

| Configuration | Entry point | RAG / `retrieve` | Planner | Reflection |
| --- | --- | --- | --- | --- |
| `baseline` | `baseline.py` | Off | Off | Off |
| `rag` | `extension.py` | On | Off | Off |
| `rag-planner` | `extension.py --planner` | On | On | Off |
| `rag-reflection` | `extension.py --reflection` | On | Off | On |
| `full` | `extension.py --planner --reflection` | On | On | On |

**How to run the tests**

**Set up the standalone agent.** Install uv and Python 3.12. For a first-time setup, copy `agent/.env.example` to `agent/.env`. If you already have an `agent/.env` file, use it.

| Service | Settings in `agent/.env`                                     | Purpose                                                      |
| ------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| Bailian | Set `BAILIAN_API_KEY` and check that `MODEL_BASE_URL` and `MODEL_NAME` match your account. | Runs the research model. RAG uses the same key for embeddings and defaults to `text-embedding-v4`. |
| Tavily  | `TAVILY_API_KEY`                                             | Searches arXiv for papers.                                   |
| Neon    | `DATABASE_URL`                                               | Stores papers and results when you add `--persist` to an individual run. |

**Run the agent on one paper.** The QA example uses a preselected paper and requires only the Bailian settings. Run it from the repository root.

```sh
uv run --directory agent --frozen python baseline.py --task examples/qa.json
```

**Run the full ablation test.** Some of the 25 runs use your paper library. Follow the root README to start the backend, then sign in with a verified account. Import or upload the SkillOpt paper and check that a library search for `SkillOpt` finds it. From the repository root, pass your library username and password as the two arguments.

```sh
./agent/run.sh 'username' 'password'
```

Each run writes `result.json` and `trace.json` to `agent/runs/ablation/<batch>/<case>/<configuration>/`.

<a id="evaluation-model-server"></a>

#### 2. Model Server Experiment

##### Environment, Data, and Comparisons

Use the shared TACC course vLLM environment and Qwen3.8-27B-AWQ-INT4. Allocate two RTX 3090 GPUs with TP=2, BF16, and 8 CPUs, with a one-hour GPU job limit. Submit CPU benchmark jobs separately. The reported environment uses vLLM 0.26.0, PyTorch 2.11.0+cu128, Transformers 5.10.4, and Triton 3.6.0. The course provides the shared environment and model weights; local compilation or downloading is unnecessary. Complete `tcloud init` first; see [server prerequisites](model-server/server-opt/README.md#prerequisites) for environment permissions.

Fix `max_model_len=36864`, `max_num_seqs=4`, and `gpu_memory_utilization=0.9`, enable prefix caching, and use the `auto` attention backend. The service's 36864-token context covers input and output combined. The benchmark clients below independently cap input at 32767 and output at 4096 tokens; **these client budgets do not lower the Agent or service output limit to 4096**. `max_num_batched_tokens` is the per-iteration scheduling budget, distinct from an output limit.

| Data / protocol | Measured requests | Purpose |
| --- | --- | --- |
| [`serial-long-copy-boundary-v2`](model-server/server-opt/evaluation/data/serial-long-copy-boundary-v2.workload.json) | 4 rounds x 6 questions: 24 measured requests. | Serial comparison for long-text quotation, field extraction, and complete-record copying. |
| `serial-long-copy-screen-v1`, a subset selected by [`quick_workload.py`](model-server/server-opt/evaluation/serial/quick_workload.py) | 2 rounds x 4 questions: 8 measured requests. | Quick serial screening of prefill budgets. |
| [`concurrent-long-copy-screen-v1`](model-server/server-opt/evaluation/data/concurrent-long-copy-screen-v1.workload.json) | 2 waves x 4 requests: 8 measured requests. | C=1 / C=4 comparison and C=4 budget comparison with a fixed workload. |

All three protocols start with three warmup requests excluded from measured statistics. Keep the 8-request screening protocol separate from the 24-request protocol when aggregating. The procedures map to the report as follows:

| Comparison | Fixed and varied settings | Reproduction instructions and report |
| --- | --- | --- |
| Serial budget screening | Serial client; budgets 2048 / 4096 / 8192. | [Procedure A](model-server/server-opt/README.md#experiment-a-serial-e00-and-prefill-budget-experiment), report section 3.1. |
| Concurrency comparison | Fixed budget 4096; change only client concurrency from C=1 to C=4. | [Procedure B](model-server/server-opt/README.md#experiment-b-concurrent-baseline), report section 3.2. |
| C=4 scheduling budget | Fixed C=4; budgets 2048 / 4096 / 8192; start a new service for each budget. | [Procedure C](model-server/server-opt/README.md#experiment-c-c4-chunked-prefill-experiment), report section 3.3. |
| GDN indexed-state and GPU N-gram speculative decoding | Historical private-runtime candidates for state access and speculative decoding, respectively. | Report sections 3.4 / 3.5, [archived results](model-server/server-opt/results/), and [reproducibility limits](model-server/server-opt/README.md#known-limitations). Complete private source/build trees are not included; the public package alone cannot rerun these candidates. |

##### Submit the Service and Separate Benchmark Client

The example starts with budget 4096 and C=4. Repeat with budgets 2048 and 8192, creating a fresh directory and service/client jobs for each, to compare scheduling budgets. Modify only the working copy, preserving the repository configuration:

```bash
BUDGET=4096
RUN_DIR="$PWD/runtime/evaluation/model-server/$(date -u +%Y%m%dT%H%M%SZ)-b$BUDGET"
mkdir -p "$(dirname "$RUN_DIR")"
test ! -e "$RUN_DIR"
cp -a model-server/server-opt "$RUN_DIR"
python3 - "$RUN_DIR" "$BUDGET" <<'PY'
import json
import sys
from pathlib import Path

root, budget = Path(sys.argv[1]), int(sys.argv[2])
for relative in ("service_config.json", "evaluation/serial/service_config.json", "evaluation/concurrency/service_config.json"):
    path = root / relative
    config = json.loads(path.read_text())
    config.update(max_num_batched_tokens=budget, profile=f"repro-b{budget}")
    path.write_text(json.dumps(config, indent=2) + "\n")
PY
cd "$RUN_DIR"
bash setup-sdk-account.sh
tcloud submit
```

Record the returned GPU job ID and replace the placeholder below. Check the service log, wait for `Application startup complete.`, and set `BASE_URL` to this run's `SERVICE_BASE_URL`. Do not reuse historical node addresses:

```bash
GPU_ID='<current GPU job ID>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-public-serve-agent-${GPU_ID}.log"
BASE_URL='http://<current node>:8000/v1'
cd "$RUN_DIR/evaluation/concurrency"
printf '%s\n' "$GPU_ID" > service-job-id.txt
printf '%s\n' "$BASE_URL" > server-url.txt
printf '4\n' > concurrency-level.txt
tcloud submit
```

Download evidence after the CPU job finishes. Replace `CLIENT_ID` with this run's CPU job ID:

```bash
CLIENT_ID='<current CPU job ID>'
tcloud ps -j "$CLIENT_ID"
tcloud cat "slurm_log/qwen-concurrency-quality-${CLIENT_ID}.log"
RESULT="$RUN_DIR/results/job-$CLIENT_ID"
mkdir -p "$RESULT"
for name in summary.json answers.jsonl workload.json warmup.json tokenization.json \
            service_config.json server-metrics-before.txt server-metrics-after.txt metrics-boundaries.jsonl; do
  tcloud download "model-server-results/job-$CLIENT_ID/$name" "$RESULT/$name"
done
tcloud download "slurm_log/qwen-concurrency-quality-${CLIENT_ID}.log" "$RESULT/client.log"
tcloud download "slurm_log/qwen-public-serve-agent-${GPU_ID}.log" "$RESULT/service.log"
```

For the concurrency comparison, rerun C=1 against the same service at budget **4096**: write `1` to `concurrency-level.txt`, run `tcloud submit` again, record the new CPU ID, and save its results separately. For serial testing, enter `$RUN_DIR/evaluation/serial`, set `service-job-id.txt` and `server-url.txt` in the same way, and write `quick` (8 requests) or `long` (24 requests) to `measurement-mode.txt` before submitting. The serial log is `qwen-latency-quality-<CPU_ID>.log`. After all runs finish and evidence is saved, run `tcloud cancel -j "$GPU_ID"` to release your own service, then return to the repository root with `cd /path/to/project`.

##### Validation, Metrics, and Limitations

Verify the actual protocol, measured request count, quality gate, absence of output truncation, `workload_sha256`, service parameters, and measurement code version. Concurrency logs should include `PROTOCOL=concurrent-long-copy-screen-v1`, `WARMUP_COMPLETE=3`, and `RUN_COMPLETE measured_requests=8 PROFILE=concurrency`. Compare TTFT, TPOT, end-to-end latency, requests/s, output tokens/s, token usage, cache hits/queries, prefill, queueing, and preemptions in `summary.json`. Map them to [Server report section 3](model-server/server-opt/reports/Server_report.md#3-experimental-results) and the [frozen results](model-server/server-opt/results/).

The model benchmark client times streaming requests and collects `/metrics` at experiment boundaries. The end-to-end Agent uses non-streaming requests and native server telemetry; keep the two TTFT definitions separate. Historical benchmark sidecar sample files are empty, so GPU utilization, GPU memory, and KV-cache peaks are unavailable. Small samples, node differences, shared load, caches, and first-run JIT can cause variation. This benchmark does not measure real Agent task throughput. The model experiment selected 8192 as a throughput-oriented configuration; web model management still deploys `server/` by default and does not automatically switch to `server-opt/` when following this section.

<a id="evaluation-end-to-end"></a>

#### 3. End-to-End Research Experiment

This experiment compares **Agent Baseline and Extension** across the paper library, TCloud dispatch, model service, citations, and independent evaluation. See the [end-to-end report](Report.pdf) for measurements and analysis. It is distinct from the five-configuration ablation above and does not assume model-server optimizations.

**View existing results online:** Open [https://8.218.149.237/](https://8.218.149.237/) and sign in with username `Researcher` (case-sensitive) and password `123456`. Open the research records and select a task to view its answer, citations, evaluation scores, and performance metrics.

##### 1. Test Cases and Paper Data

The [experiment manifest](docs/evaluation/researcher-20261123.json) records the original questions, per-workflow paper order, PDF SHA-256 values, budgets, and historical task/evaluation IDs from the `Researcher` account. Rerun with your own verified account; neither that account's password nor a database copy is needed. The manifest's `cases` contain paired test cases, while `runs` contain sanitized historical metric snapshots.

| Task type | Case IDs | Question scope | Initially selected papers |
| --- | --- | --- | --- |
| Single-paper QA | `QA01`-`QA03` | FlashAttention-2 computational complexity, Longformer local/global attention, and Performer approximation properties | 1 per case |
| Single-paper summary | `SUM01`-`SUM03` | Transformer architecture and experiments, Transformer translation results and limitations, and FlashAttention methods and evidence | 1 per case; the first two use the same Transformer PDF |
| Multi-paper review | `REV01`-`REV04` | Three linear-attention papers, five efficient-attention papers, and FlashAttention comparisons at two levels of detail | 3, 5, 2, and 2, respectively |
| Domain survey | `SUR01`-`SUR05` | LoRA/QLoRA, self-evolving Agent skills, sparse attention, hallucination detection and mitigation, and RAG | None; the Agent searches for papers |

Run each case once with Baseline and once with Extension, totaling 30 research tasks. The manifest also preserves six historical Extension runs without Baseline counterparts for auditing; exclude them from paired comparisons.

Download these **specific arXiv versions**, upload them to your paper library, and wait until all are `ready`. Alternatively, import them individually through the [import API](docs/api-contract.md). Complete titles, page counts, and hashes are in the manifest's `papers` section.

| Paper | arXiv version |
| --- | --- |
| Attention Is All You Need | `1706.03762v7` |
| Big Bird | `2007.14062v2` |
| FlashAttention-2 | `2307.08691v1` |
| FlashAttention | `2205.14135v2` |
| Linformer | `2006.04768v3` |
| Longformer | `2004.05150v2` |
| Rethinking Attention with Performers | `2009.14794v4` |
| Transformers are RNNs | `2006.16236v3` |

Paginate through `GET /api/v1/papers?limit=50&offset=0` to check `sha256`. Do not reuse the historical account's paper UUIDs. The commands below map hashes to UUIDs belonging to the current account. Record any byte differences as data changes, even for the same arXiv version. Survey search results change over time; original search responses and all external PDFs are not bundled, so the retrieved corpus may differ.

##### 2. Runtime Environment and Configuration

Complete the Getting Started configuration for accounts, the paper library, TCloud, Tavily, and the evaluation Worker. Launch the course Qwen service following the [model-server instructions](model-server/README.md), wait until model management shows it as ready, and keep the same service running for both tasks in each pair. Historical experiments used `qwen3.8-27b` at temperature `0`, with TACC CPU Agent jobs accessing the GPU model service. ECS does not need direct access to the GPU node's private address. Record `git rev-parse HEAD`, the GPU job ID, model version, and service launch configuration. Historical tasks did not retain all model-service launch parameters, so they do not establish whether the optimized service was used.

Set the following experiment parameters in the private `backend/.env`, then restart the API, Agent Runner, and evaluation Worker. If using a launcher, rerun the platform-specific `start` command. See [service startup](docs/service_launch.md) for ECS service management.

```dotenv
TASK_RUNNER=agent
AGENT_DISPATCH_ENABLED=true
AGENT_TRANSPORT=tcloud
AGENT_SEARCH_MAX_PAPERS=5
AGENT_MAX_STEPS=200
AGENT_TIMEOUT_SECONDS=1800
AGENT_OUTPUT_TOKENS=16384
AGENT_CONTEXT_TOKENS=32000
AGENT_PERSIST=false
EVALUATION_ENABLED=true
EVALUATION_BASE_URL=https://api.deepseek.com
EVALUATION_MODEL=deepseek-flash
EVALUATION_TIMEOUT_SECONDS=180
EVALUATION_MAX_INPUT_BYTES=256000
EVALUATION_DAILY_LIMIT=50
```

Configure `EVALUATION_API_KEY`, `TAVILY_API_KEY`, and TCloud/library connection settings privately as described in Getting Started. Extension also needs valid Bailian embedding credentials for `text-embedding-v4` with 1024 dimensions; see [Agent configuration](agent/README.md) and [TACC configuration](tacc/TACC.md). Point `AGENT_TCLOUD_MODEL_ENV_FILE` to a private file containing these credentials. Keep keys out of experiment manifests and results.

Set `AGENT_SEARCH_MAX_PAPERS` explicitly to **5** rather than retaining the example configuration's value. Other step and timeout settings are global ceilings; actual budgets depend on the number of initially selected papers and the additional-search allowance:

| Initial papers | Maximum research papers | Agent step limit | Task timeout (seconds) |
| --- | --- | --- | --- |
| 0 | 5 | 72 | 600 |
| 1 | 6 | 80 | 660 |
| 2 | 7 | 88 | 720 |
| 3 | 8 | 96 | 780 |
| 5 | 10 | 112 | 900 |

Both workflows enable additional search, use `context_policy: "compact"` and `context_finalize_ratio: 0.9`, and allow up to 16384 output tokens per request. Baseline sets `planner` / `reflection` to `false`; Extension sets both to `true`. The manifest preserves each request's configuration, which the commands below use directly. Inspect traces to determine whether enabled features actually execute.

##### 3. Submit, Wait, and Save

Run the following in the **Chrome / Edge developer-tools Console on the signed-in web application**. It uses the current session and CSRF token, so no account password is entered in the code. Select `docs/evaluation/researcher-20261123.json` from your local repository when prompted. By default, it reruns only the `QA01` pair. After verifying the workflow, edit `caseIds` to cover all cases in batches, such as `["SUM01", "SUM02", "SUM03"]`. Set it to `null` to run all 15 pairs sequentially only if the model service has enough time remaining. Otherwise, renew the GPU service between batches and record the new service details, keeping each pair on the same service instance. Reruns consume model, search, cluster, and user quotas. The default per-user daily limits are 50 research tasks and 50 new evaluation versions, including quota already used.

```javascript
(async () => {
  const caseIds = ["QA01"];
  const fixture = await new Promise((resolve, reject) => {
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = ".json";
    picker.onchange = async () => {
      try { resolve(JSON.parse(await picker.files[0].text())); }
      catch (error) { reject(error); }
    };
    picker.oncancel = () => reject(new Error("No fixture selected"));
    picker.click();
  });
  const api = async (path, options = {}) => {
    const response = await fetch(`/api/v1/${path}`, {
      credentials: "same-origin", ...options
    });
    if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
    return response.json();
  };
  const {csrf_token} = await api("auth/me");
  const papersByHash = new Map();
  for (let offset = 0; ; offset += 50) {
    const page = await api(`papers?limit=50&offset=${offset}`);
    for (const paper of page.items) {
      if (paper.status === "ready") papersByHash.set(paper.sha256, paper.id);
    }
    if (offset + page.items.length >= page.total) break;
  }
  const cases = fixture.cases.filter(item => caseIds === null || caseIds.includes(item.id));
  if (!cases.length || (caseIds !== null && cases.length !== caseIds.length)) {
    throw new Error("Check caseIds against the fixture");
  }
  for (const item of cases) for (const variant of Object.values(item.variants)) {
    for (const hash of variant.paper_sha256s) {
      if (!papersByHash.has(hash)) throw new Error(`Missing ready PDF: ${hash}`);
    }
  }
  window.evaluationRuns ??= [];
  for (const item of cases) for (const workflow of ["baseline", "extension"]) {
    const variant = item.variants[workflow];
    const accepted = await api("agent-research", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf_token},
      body: JSON.stringify({question: item.question, allow_search: true,
        paper_ids: variant.paper_sha256s.map(hash => papersByHash.get(hash)),
        research: variant.research})
    });
    const saved = {case_id: item.id, workflow, task_id: accepted.task_id};
    window.evaluationRuns.push(saved);
    const deadline = Date.now() + 60 * 60 * 1000;
    while (true) {
      saved.record = await api(`agent-research/${saved.task_id}`);
      saved.task = await api(`tasks/${saved.task_id}`);
      const researchDone = ["succeeded", "failed"].includes(saved.record.status);
      const judge = saved.record.metrics.evaluation;
      if (researchDone && !["pending", "running"].includes(judge.status)) break;
      if (Date.now() > deadline) throw new Error(`Wait expired; keep task ${saved.task_id}`);
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
    console.log(item.id, workflow, saved.task_id, saved.record.status,
      saved.record.result?.stop_reason, saved.record.metrics.evaluation.status);
  }
  copy(JSON.stringify(window.evaluationRuns, null, 2));
  console.log("Copied results. Save under runtime/evaluation/; do not commit private answers.");
})();
```

Save the clipboard contents to `runtime/evaluation/rerun.json`. The script retains failed tasks and stops further submissions on an HTTP error or wait timeout. Submitted IDs remain in `window.evaluationRuns`; run `copy(JSON.stringify(window.evaluationRuns, null, 2))` at any time to save progress. Refreshing the page clears this variable, so keep the page open during long experiments. A wait timeout does not cancel remote jobs. Check existing task IDs before continuing to avoid duplicate submissions.

You may also create tasks individually in the web interface: copy the original `question` from the manifest, select papers in the order given by that workflow's `paper_sha256s`, and apply the switches above. Complete one workflow before submitting the other and save both task IDs. A complete comparison must cover all cases, including unsuccessful or low-scoring runs. To evaluate concurrency, design a separate experiment with fixed concurrency and keep its results separate from these serial runs.

##### 4. Collect and Aggregate Metrics

| Data | Source and definition |
| --- | --- |
| Five-dimensional DeepSeek evaluation | `GET /api/v1/tasks/{id}/evaluation` and task detail `metrics.evaluation`. Save `evaluation_id`, `prompt_version`, `rubric_version`, and `assessment`. Each dimension scores 0-5, with weights: factual/evidence consistency 30, citation support 30, task completion 20, analysis quality 15, and clarity 5. Total score: `sum(dimension_score * weight / 5)`. |
| Agent steps, calls, and tokens | `metrics.agent` from `GET /api/v1/agent-research/{id}`. Agent execution time is `result.usage.elapsed_seconds`. Chat token counts exclude independent evaluation and separately recorded embedding usage. |
| Platform end-to-end time | `stats.end_to_end_ms / 1000` from `GET /api/v1/tasks/{id}`. Includes dispatch, queueing, and result return, but excludes subsequent independent evaluation. Keep it separate from Agent execution time. |
| TTFT, TPOT / mean ITL, and tokens/sec | Task detail `metrics.model_server`. Native sources are `metrics.time_to_first_token_ms`, `metrics.mean_itl_ms`, and `metrics.tokens_per_second`, respectively. For group comparisons, take the arithmetic mean of per-task valid-request means and report sample counts, sources, and missing data. |
| Cache hit/query tokens and hit ratio | `metrics.model_server.cache_hit_tokens`, `cache_query_tokens`, and `cache_hit_ratio`. Compute group hit ratio as `sum(hit_tokens) / sum(query_tokens)`, check `cache_usage_complete`, and avoid averaging percentages directly. |
| GPU utilization | `metrics.model_server.gpus` contains completion-time snapshots of allocated devices. Retain device UUIDs and sampling times; these are neither per-task average nor peak utilization. |

Within each task type, pair runs by the same question and PDF hash set, aggregate Baseline / Extension separately, and report sample sizes and the sign of `Extension - Baseline`. Record paper order separately; the historical manifest preserves actual order without sorting. Check task `status` and Agent `stop_reason` independently: `succeeded` does not establish that the research is complete. Do not replace evaluation failures, `insufficient_evidence`, or missing metrics with zero.

Model-service load, caches, TACC queueing, dynamic search, PDF retrieval, and model/evaluation-service updates affect reruns. Even temperature 0 does not guarantee identical wording or numerical results. Add multiple paired repetitions, alternate execution order, and report distributions; a single round does not establish a causal improvement. See the [experiment report](Report.pdf) for numerical results and their scope, and the [Server report](model-server/server-opt/reports/Server_report.md) for the independent model-server experiment.
