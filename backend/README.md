# 后端

后端负责账号、论文库、研究任务、结果及异步评分；研究由独立 Agent 执行。本文集中说明启动、配置、运行限制和任务指标。完整业务接口见 [HTTP API 契约](../docs/api-contract.md)，TACC 环境与作业操作见 [TACC 指南](../tacc/TACC.md)。

<a id="1-首次启动"></a>

## 首次启动

需要 Python 3.11+、uv 和 PostgreSQL；独立 Agent 使用自己的 Python 3.12 环境。从项目根目录执行：

```sh
cd backend
uv sync --locked
cp -n .env.example .env
```

PowerShell 用 `if (!(Test-Path .env)) { Copy-Item .env.example .env }` 代替复制命令。先按下节补齐私有配置，再启动数据库、迁移和 API；使用现有 PostgreSQL 时跳过 Compose。

```sh
docker compose up -d --wait postgres
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

以下命令均在 `backend/` 下分别保持运行，按功能启用：

| 进程 | 命令 | 用途 |
| --- | --- | --- |
| Parser | `uv run --locked python -m app.parser_worker` | 校验 PDF，提取标题、页数 |
| 研究 Worker | `uv run --locked python -m app.runner_worker` | 领取任务、派发 Agent、接收结果 |
| 邮件 Worker | `uv run --locked python -m app.mail_worker` | 发送注册验证、密码找回邮件 |
| Import Worker | `uv run --locked python -m app.import_worker` | 下载选定版本的 arXiv 论文 |
| 评分 Worker | `uv run --locked python -m app.evaluation_worker` | 异步调用 DeepSeek 评分 |

修改配置后重启对应 API 和 Worker。`GET /health` 检查存活，`GET /ready` 检查数据库连接和迁移。

<a id="10-账号qq-邮件与私有数据2026-11-14"></a>

## 配置与账号

字段按类别列在 [.env.example](.env.example)，校验范围和程序默认值见 [Settings](src/app/config.py)。环境变量优先于 `backend/.env`；样例中的显式值会覆盖程序默认值。样例中的密钥、邮箱、模型和派发路径仍需自行填写或核对。

- **数据库与存储**：API、论文库入口和 Worker 共用 `DATABASE_URL`、`STORAGE_ROOT` 及鉴权配置。样例数据库名、用户名、密码均为 `literature_assistance_system`，宿主机端口为 `55432`；部署时更换密码，并保持 Compose 与连接串一致。默认 PDF 路径为 `backend/runtime/storage/uploads/<UUID>.pdf`；生产使用绝对存储路径。
- **浏览器访问**：`FRONTEND_PUBLIC_URL` 与实际浏览器来源一致，`CORS_ORIGINS` 为 JSON 数组。统一使用一个主机名，避免混用 `localhost` 和 `127.0.0.1`。公网使用 HTTPS 和 `AUTH_COOKIE_SECURE=true`；本地回环 HTTP 将该值改为 `false`，样例当前为 `true`。
- **账号与会话**：`AUTH_RATE_KEY`、`AUTH_CSRF_KEY` 使用独立的至少 32 字节随机密钥。登录用户名区分大小写；受保护接口检查会话和资源归属，网页写请求还需可信 Origin 与 `X-CSRF-Token`。
- **注册邮件**：使用 QQ 邮箱时填写 `SMTP_HOST=smtp.qq.com`、`SMTP_PORT=465`、相同的 `SMTP_USERNAME`/`SMTP_FROM` 和 SMTP 授权码 `SMTP_AUTH_CODE`。`MAIL_OUTBOX_KEY` 使用独立 Fernet 密钥，队列中仍有加密邮件时保持不变。

在本机终端生成密钥后写入私有 `.env`，不要提交或粘贴到日志中：

```sh
uv run --locked python -c "import secrets; from cryptography.fernet import Fernet; print('AUTH_RATE_KEY=' + secrets.token_urlsafe(32)); print('AUTH_CSRF_KEY=' + secrets.token_urlsafe(32)); print('MAIL_OUTBOX_KEY=' + Fernet.generate_key().decode())"
```

## 论文与检索

- 用户上传与 arXiv 导入的 PDF 均限制为 **50 MB（52,428,800 bytes）**。反向代理也需放行对应请求体并为 multipart 留余量。Parser 只负责元数据，不再生成本地 chunk；历史 `paper_chunks` 与旧引用结构保留兼容。
- 设置 `ARXIV_ENABLED=true`、`ARXIV_CONTACT_EMAIL`，运行 Import Worker 和 Parser 后可搜索、导入明确版本的 arXiv 论文。Agent 外部搜索还需后端私有 `TAVILY_API_KEY`。
- 用已验证账号登录、上传或导入 PDF，再向 `POST /api/v1/agent-research` 提交问题和可选论文。最多预选 20 篇；`allow_search` 决定是否允许追加检索。写请求重试沿用同一 `Idempotency-Key`。结果中的库内引用可回到 PDF 对应页。

<a id="8-独立-agent-配置"></a>
<a id="agent-dispatch"></a>

## Agent 派发与预算

API 与研究 Worker 使用相同的 `TASK_RUNNER=agent`、`AGENT_DISPATCH_ENABLED` 和传输配置。派发需要显式启用且执行端已准备好；内置 LangGraph 流程已移除。交换目录默认是 `STORAGE_ROOT/agent-exchange`，可由 `AGENT_EXCHANGE_ROOT` 覆盖。

| `AGENT_TRANSPORT` | 条件与配置 |
| --- | --- |
| `manual` | 外部执行端从 outbox 读取输入，在对应 inbox 交付版本化结果；后端不会自行运行 Agent。 |
| `local` | `AGENT_LOCAL_ROOT` 指向兼容的独立 Agent，`AGENT_LOCAL_PYTHON` 指向其解释器；相对路径从 `backend/` 解析。Windows 通常为 `../agent/.venv/Scripts/python.exe`，Linux/macOS 为 `../agent/.venv/bin/python`。 |
| `tcloud` | Worker 机器已初始化课程 SDK，`AGENT_TCLOUD_ENV_NAME` 指向可用环境；计算节点能通过 `AGENT_LIBRARY_PUBLIC_URL` 的 HTTPS 地址访问论文库。`AGENT_TCLOUD_MODEL_ENV_FILE` 可指定 Worker 上的私有百炼配置，为作业申请临时密钥。 |
| `tacc` | SSH/Slurm helper 模式；配置 `AGENT_TACC_HOST`、远端绝对路径 `AGENT_TACC_HELPER`/`AGENT_TACC_CONFIG`，以及必要的 `AGENT_TACC_PYTHON`。 |

主 API 通常监听 `127.0.0.1:8000`。本地联调如需向计算节点暴露论文库，可单独运行 `app.main:create_library_app` 于 `127.0.0.1:8001` 并通过 HTTPS 隧道转发。作业使用 Worker 签发的只读凭据，浏览器仍使用自己的会话。

### 限额与超时

下表列出**当前配置样例值**。省略字段时的程序默认值可能不同，例如每日研究任务默认 50 次，样例为 100 次。

| 配置 | 样例值 | 含义 |
| --- | ---: | --- |
| `USER_ACTIVE_TASKS` / `USER_ACTIVE_IMPORTS` | 5 / 5 | 每用户排队及执行中的研究 / 导入上限 |
| `USER_DAILY_TASKS` | 100 | 每用户每 UTC 日新建研究任务数；幂等重放不另计 |
| `AGENT_MAX_STEPS` | 200 | 任务步数上限，允许 1–200 |
| `AGENT_SEARCH_MAX_PAPERS` | 20 | 允许检索时追加的论文容量；预选与检索合计最多 20 |
| `AGENT_TIMEOUT_SECONDS` | 1800 | 任务执行时限上限，单位秒 |
| `AGENT_OUTPUT_TOKENS` / `AGENT_CONTEXT_TOKENS` | 16384 / 32000 | 单次主模型输出上限 / 上下文预算 |
| `AGENT_TCLOUD_SUBMIT_TIMEOUT_SECONDS` | 180 | SDK 同步文件、准备环境和提交的等待上限，单位秒 |
| `AGENT_TRANSPORT_TIMEOUT_SECONDS` / `AGENT_POLL_SECONDS` | 30 / 2 | 普通传输超时 / 轮询间隔，单位秒 |
| `AGENT_RESULT_MAX_BYTES` | 16777216 | Agent 结果文件字节上限 |
| `PARSER_TIMEOUT_SECONDS` | 120 | PDF 元数据解析超时，单位秒 |

令 `N` 为预选论文数；允许搜索时取 `min(20, 预选数 + AGENT_SEARCH_MAX_PAPERS)`。统一研究和旧 summary/QA/review 接口都使用：

- 步数：`min(AGENT_MAX_STEPS, 32 + 8 * N)`；禁止搜索时，1 / 5 / 20 篇分别为 40 / 72 / 192 步。
- 执行时限：`min(AGENT_TIMEOUT_SECONDS, 300 + 60 * N)` 秒，从 Worker 首次领取开始计时。
- 单次主模型输出：`min(AGENT_OUTPUT_TOKENS, AGENT_CONTEXT_TOKENS - 2048)`，与论文数无关，不是任务总 Token 额度；辅助调用可使用更小预算。

TACC 与课程自定义模型路径另外将有效上下文限制为 36864，输出取 `min(清单输出预算, 16384, 有效上下文 - 2048)`。样例 32000 上下文、16384 输出为输入保留 15616 Token；提高输出会挤压证据和历史空间，不能保证任意长回答都完整。模型因长度截断仍返回 `output_truncated`。

### 排队与恢复

共享同一数据库的研究 Worker 默认合计并发 2 项，可在界面调为 1–4；新设置在下一次领取时生效，降低并发不会中止已派发任务。每用户活跃额度独立于全局并发。每日研究额度按现存任务记录计数，删除记录可能降低当天计数。

Worker 重启沿用任务期限和派发标识，优先恢复已启动任务。详情中的 `agent.dispatch_id`、`remote_job_id` 可用于排查；提交回执不明时保留交换目录。限额更改仅影响新任务，已签名清单不变，失败任务需重新提交。`AGENT_RETENTION_SECONDS` 默认 7 天、最少 1 天，仅供显式清理使用。旧 mock/LangGraph 未完成任务会标为 `RUNNER_RETIRED`，历史终态结果仍可读取。交换和恢复协议见 [Agent 对接契约](../docs/agent-backend-integration.md)。

<a id="deepseek-evaluation"></a>

## DeepSeek 评分

评分独立于研究结果和执行预算：失败不会覆盖研究正文。先迁移数据库，在私有 `.env` 中配置 `EVALUATION_ENABLED=true`、`EVALUATION_BASE_URL`、账户实际可用的 `EVALUATION_MODEL`、`EVALUATION_API_KEY`，再启动评分 Worker 并重启 API、研究 Worker。模型须支持非流式 Chat Completions 和 JSON 输出；评分密钥只保留在后端。

启用后仅自动评分新交付的结果，不扫描历史任务；历史结果通过 POST 主动申请。可用 `uv run --locked python -m app.evaluation_worker --once` 单次处理队列。ECS 的 [systemd 示例](ops/acs-evaluation.service) 可从仓库根目录以 root 安装，路径不同需相应调整：

```sh
install -m 644 backend/ops/acs-evaluation.service /etc/systemd/system/acs-evaluation.service
systemctl daemon-reload
systemctl enable --now acs-evaluation.service
journalctl -u acs-evaluation.service -n 50 --no-pager
```

该服务随 `acs-runner.service` 停启，评分失败不停止研究 Worker。暂停评分时停止评分服务、关闭 `EVALUATION_ENABLED` 并重启 API/研究 Worker；历史报告仍可查询。

### 评分标准与证据

| 字段 | 维度 | 权重 |
| --- | --- | ---: |
| `grounded_correctness` | 事实、数字与证据一致性 | 30% |
| `citation_support` | 引用是否可定位并支持对应论断 | 30% |
| `task_completion` | 是否回答问题及要求的子任务 | 20% |
| `analysis_quality` | 综合分析、比较条件、局限与不确定性 | 15% |
| `clarity` | 表达清晰、结构合理 | 5% |

每维 0–5 分并附原因，0 表示缺失或根本错误，3 表示基本合格，5 表示给定证据下表现优秀。后端计算 `sum(score * weight / 5)`，得到保留一位小数的 0–100 综合分。`assessment=insufficient_evidence` 时各分数为 `null`，不能视为零分；评分是模型在有限证据下的判断，不等同于准确率。

输入包含完整回答、Agent 返回的全部引用及可读取的被引原始页。库内文件须属于任务用户、与任务关联并通过哈希核验；只提取被引页，不读整库、不抓取外部 URL。库内展示引用用 `C` 键，其余原生引用用稳定 `E` 键。原始页提取使用隔离子进程，无页数上限，旧 `EVALUATION_MAX_ORIGINAL_PAGES` 不再生效；单页文本超过 16000 UTF-8 字节会跳过，提取总结果上限 1 MB，另有超时和平台资源限制。

报告保留维度原因、总结、问题及严重程度、改进建议、引用/原文检查、证据限制和用量。`evaluation_scope=evidence_only` 表示只有返回摘录，`original_pages` 表示获得部分被引页上下文，不代表所有引用都已验证。逐引用状态为 `matched/not_found/unavailable`；未匹配不直接等于伪造。证据快照和摘要保存后用于重试。

### 评分接口与限额

以下路径均为 `/api/v1/tasks/{task_id}/evaluation`：

| 请求 | 用途 |
| --- | --- |
| `GET` | 最新版本及完整报告，无记录时为 `not_requested` |
| `GET ?evaluation_id=<UUID>` | 查询本任务指定历史版本 |
| `POST`，无请求体 | 返回 202，申请、复用版本或在次数范围内重试失败版本 |

接口要求登录与任务归属；POST 还需 Origin、CSRF。报告版本字段为 `id`，任务详情摘要中为 `evaluation_id`。返回状态、模型/评分标准/提示词版本、输入与证据摘要、尝试次数、脱敏错误码、报告、用量和时间；不返回密钥、原始输入快照或内部路径。

评分状态为 `not_requested`、`pending`、`running`、`succeeded`、`failed`、`skipped`；`succeeded` 还需结合 `assessment` 区分已评分与证据不足。

| 配置 | 样例值 | 限制 |
| --- | ---: | --- |
| `EVALUATION_TIMEOUT_SECONDS` | 180 | 单次评分请求超时，单位秒 |
| `EVALUATION_EVIDENCE_TIMEOUT_SECONDS` | 60 | 原始证据处理超时，单位秒 |
| `EVALUATION_DAILY_LIMIT` | 50 | 每用户每 UTC 日新评分版本数 |
| `EVALUATION_MAX_ATTEMPTS` | 3 | 每版本尝试次数 |
| `EVALUATION_MAX_INPUT_BYTES` | 256000 | 完整请求 UTF-8 字节上限，含系统提示、正文和证据 |
| `EVALUATION_MAX_OUTPUT_TOKENS` | 16384 | 单次输出上限，与 Agent 输出预算无关 |
| `EVALUATION_MAX_RESPONSE_BYTES` | 262144 | 响应字节上限 |

未配置时，程序默认输入上限为 64000 字节、输出为 4096 Token；显式配置优先。超限会失败，不会静默裁掉证据。额度以独立配额记录原子预留，复用和同版本重试不另占新版本额度，删除任务不退还；队列重试可能跨天执行，没有全站费用上限。

HTTP 429/5xx、超时、网络错误和非法结构输出在尝试预算内退避重试。鉴权、请求参数、输出截断、输入/响应超限需检查配置或内容。租约过期可恢复，旧 Worker 不能覆盖新状态；进程在请求后崩溃仍可能重复付费调用。无可用研究结果记为 `skipped/NO_USABLE_RESULT`，有用的部分结果仍可评分。删除任务级联删除评分，但无法撤销已发出的模型请求。

模型、提示词、评分标准或评分限额变化会形成新配置身份；旧排队版本以 `EVALUATION_CONFIG_CHANGED` 结束，需显式申请新版本。

## 任务指标与前端接入

已登录用户从 `GET /api/v1/agent-research/{task_id}` 获取当前研究详情，旧任务使用 `GET /api/v1/tasks/{task_id}`。两者的 `metrics` 结构相同，列表不返回指标。GET 只读数据库，不执行评分、不查询模型或 TACC，也不是实时 GPU 监控。

`metrics.schema_version=task-metrics-v1`，包含 `evaluation`、`agent`、`model_server` 三组。完整字段以 `/openapi.json` 的 `TaskMetrics` 和 [指标契约](src/app/task_metrics/contracts.py) 为准。

响应片段如下，省略其他字段；示例缓存只覆盖 2 次调用，不能代表完整任务：

```json
{
  "metrics": {
    "schema_version": "task-metrics-v1",
    "evaluation": {"status": "pending", "overall_score": null},
    "agent": {"agent_steps": 8, "model_calls": 10, "tool_calls": 7},
    "model_server": {
      "status": "partial",
      "ttft_ms": {"mean": 120, "samples": 9,
        "source": "metrics.time_to_first_token_ms", "unavailable_reason": null},
      "cache_hit_tokens": 740,
      "cache_query_tokens": 1000,
      "cache_hit_ratio": 0.74,
      "cache_measured_model_calls": 2,
      "cache_usage_complete": false,
      "gpus": []
    }
  }
}
```

### 展示字段

下表路径相对于 `metrics`：

| 数据 | 字段 | 单位或含义 |
| --- | --- | --- |
| 五维评分 | `evaluation.dimensions.<评分字段>.score/reason` | 0–5 分及原因，字段见评分标准 |
| 综合评分 | `evaluation.overall_score` | 0–100，使用后端计算值 |
| 评分版本与状态 | `evaluation.evaluation_id/status/assessment` | 最新创建版本，包含排队中的新版本 |
| 评分配置 | `evaluation.enabled/configured/model/provider` | 当前可用状态与所选版本的模型信息 |
| Agent 步数 / 模型 / 工具调用 | `agent.agent_steps/model_calls/tool_calls` | 次数，步数不必等于模型调用数 |
| 输入 / 输出 / 总 Token | `agent.input_tokens/output_tokens/total_tokens` | 不含独立 DeepSeek 评分消耗 |
| 普通 Token 完整性 | `agent.token_usage_complete` | 是否完整报告用量 |
| TTFT | `model_server.ttft_ms.mean` | ms |
| TPOT / mean ITL | `model_server.tpot_ms.mean` / `mean_itl_ms.mean` | ms/token / ms |
| 输出速度 | `model_server.tokens_per_second.mean` | 输出 tokens/sec |
| 每张 GPU 利用率 | `model_server.gpus[].utilization_percent` | 0–100，设备标识为 `uuid` |
| 缓存命中 / 查询 Token | `model_server.cache_hit_tokens/cache_query_tokens` | 有效配对请求的缓存命中 / prompt Token 合计 |
| 缓存命中率 | `model_server.cache_hit_ratio` | 0–1，展示时转百分比 |

`evaluation` 还返回 `score_max`、`overall_score_max`、`weights`、模型/提示词版本和 `error_code`；Agent 的 `available/unavailable_reason` 说明是否已有结果用量。失败研究若保存了结果，仍可有用量。

### 性能与缓存口径

- 每个性能聚合为 `{mean, samples, source, unavailable_reason}`。仅对相同 `source` 的有效调用求算术平均；`NO_SAMPLES` 表示未采集，`MIXED_SOURCES` 表示口径不同，均值均为 `null`。逐调用数据在 `requests[]`，`call_index` 从 1 开始并包含失败调用。
- TTFT 优先读取 `metrics.time_to_first_token_ms` 等原生字段；课程 vLLM 定义为调度至首 Token，不是客户端耗时。TPOT 优先显式原生 TPOT，其次原生 `mean_itl_ms`，最后流式事件近似值；独立 mean ITL 不从 TPOT 反推。吞吐量优先原生 `tokens_per_second`，回退为 `metrics.telemetry.request.server_output_tokens_per_second`。实际路径保留在 `source/sources`。
- 非流式调用仍可读取服务端原生计时，但通常没有流式事件近似值；不根据 Token 或总耗时估算缺失值。输出速度不是整个服务吞吐量，也不保证是纯 Decode 速度。
- GPU 来自 `metrics.telemetry.gpu_snapshot.gpus`，任务级保留各设备最近一次读数及 `sampled_at/call_index`。这是响应完成时整张已分配设备的采样快照，可能含其他进程，不是任务平均、峰值或显存占用率；未返回的设备不能推断。
- 缓存优先读取 `usage.prompt_tokens_details.cached_tokens` 与 `usage.prompt_tokens`，其次 `metrics.telemetry.request.cache_hit_tokens/cache_query_tokens`；历史记录也可使用已保存的 SDK 显式统计。仅接受非负整数且命中数不大于查询数的完整配对，不使用全局缓存计数、不把缺失填零。
- 缓存命中率为 `sum(命中) / sum(查询)`，不是请求命中率的平均值；查询数含命中部分，不等于未命中 Token。20/100 与 720/900 合计为 74%。`cache_measured_model_calls` 是有效配对次数，`cache_usage_complete=false` 时只代表部分请求；普通 `token_usage_complete` 不能替代它。无配对时三个缓存值为 `null`，查询合计为 0 时比率为 `null`。

`model_server.status` 为 `available/partial/unavailable`，配合 `model_calls_total`、`observed_model_calls`、`measured_model_calls` 判断覆盖；缓存另有 `cache_unavailable_reason`。未采集不等于研究失败。空值显示 `—`，真实 0 必须保留。

### 采集与页面刷新

后端管理的 TCloud 作业通过 `run_job.py` 包装，在模型 SDK 解析响应时将白名单遥测保留到 `response_metadata.server_metrics`，格式为 `backend-model-metrics-v1`，随 Agent trace/result 回传，无需数据库迁移。部署后重启 API/研究 Worker，仅新暂存的作业安装采集；其他传输可读取同格式，但不自动安装。上游未提供的历史性能/GPU 无法补采，普通 usage 中的显式缓存统计仍可使用。

前端复用现有带 Cookie、CSRF 和取消信号的 `request()`，直接读取响应体的 `record.metrics`，无需解析原始 trace 或暴露模型密钥。仅在研究 `queued/running` 或评分 `pending/running` 时继续串行轮询；请求结束后再安排下一次，建议间隔 30 秒，切换任务/退出时取消。

- 评分 `not_requested`、`failed/skipped` 或 `insufficient_evidence` 不显示零分；后两类不能遮挡研究正文。新评分排队时不把旧版本分数当作新分数，关闭评分后仍可展示历史报告。
- 用户主动点击评分才 POST；收到 202 后重读详情并恢复评分轮询。完整报告按摘要的 `evaluation_id` 获取，避免跨版本。报告文本作为不可信内容渲染，不执行原始 HTML。
- 401 处理会话失效；404 表示任务/版本不存在或无权访问；409 `EVALUATION_NOT_READY` / `EVALUATION_ATTEMPTS_EXHAUSTED` 分别表示无可评分结果 / 重试耗尽；429 `DAILY_EVALUATION_LIMIT` 不循环重试；503 `EVALUATION_NOT_CONFIGURED` 检查配置。网络错误保留最近内容，可记录请求 ID，不记录凭据或跨账号缓存任务。

## 运维与验证

<a id="4-迁移维护"></a>

### 数据库与备份

升级前备份数据库、PDF 和私有配置，再执行 `alembic upgrade head`、`alembic current`、`alembic check`。当前 head 为 `20261122_0015`，将任务步数约束提高到 200；存在大于 100 步任务时禁止降级到 0014。早于账号迁移 `20261114_0004` 的非空匿名业务数据需单独迁移或受控重置，不能直接覆盖。详见 [数据库设计与升级边界](../docs/database-design.md#114-0004-升级重置与回退边界)。

<a id="5-验证与边界"></a>

### 验证与排障

```sh
uv run --locked python -B -m unittest discover -s tests -v
```

数据库测试会清理专用测试库，勿指向业务数据。`AGENT_TEST_DATABASE_URL` 使用回环地址的 `agent_bridge_tests` 库，账号及归属测试分别使用 `AUTH_TEST_DATABASE_URL`/`OWNERSHIP_TEST_DATABASE_URL` 和对应隔离库。评分、指标及真实 SDK 模拟测试分别在 `test_evaluations.py`、`test_evaluation_postgres.py`、`test_task_metrics*.py`、`test_task_cache_metrics.py`、`test_model_telemetry_sdk.py`；SDK 测试需独立 Agent 依赖，使用内存 HTTP 模拟，不调用真实模型。

排障先查 `/ready`、对应 Worker 状态、任务执行记录与脱敏 `error_code`。`output_truncated` 检查模型实际输出/上下文限制和新任务清单；评分输入超限检查 `EVALUATION_MAX_INPUT_BYTES`；`EVALUATION_CONFIG_CHANGED` 需申请新评分版本。修改 `.env` 不会重写既有任务的冻结预算。

<a id="104-已有开发库的受控重置"></a>

### 开发库重置与代码入口

日常用 `docker compose stop postgres` 或 `docker compose down` 保留数据卷。确需清空开发库时先停服务、备份，再用 `uv run --locked python -m app.reset_data --database <库名> --storage <存储绝对路径>` 预览；确认后追加 `--execute`。

| 目录 | 职责 |
| --- | --- |
| [api](src/app/api/) / [auth](src/app/auth/) | HTTP、账号与 Agent 论文库授权 |
| [papers](src/app/papers/) / [sources](src/app/sources/) | PDF、元数据与 arXiv 导入 |
| [tasks](src/app/tasks/) / [agent_bridge](src/app/agent_bridge/) | 配额、幂等、租约、派发及结果校验 |
| [evaluations](src/app/evaluations/) / [task_metrics](src/app/task_metrics/) | 异步评分与任务指标汇总 |
| [db](src/app/db/) / [alembic](alembic/) | 数据模型与迁移 |
