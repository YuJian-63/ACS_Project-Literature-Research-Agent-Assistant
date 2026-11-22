# 前后端 API 契约

网页通过统一研究接口提交任务，独立 Agent 通过只读接口访问论文库。字段以主 API 的 `/docs`、`/openapi.json` 和下文模型链接为准。[启动与联调](service_launch.md) · [TACC 指南](../tacc/TACC.md)

## 1. 请求与响应

- 下文业务路径省略 `/api/v1`；论文、任务等实体 ID 为 UUID，私有资源按用户隔离，越权查询返回 404。
- 浏览器携带 HttpOnly 会话 Cookie；业务写请求的 `Origin` 须与 `FRONTEND_PUBLIC_URL` 一致，并将登录或 `/auth/me` 响应中的 `csrf_token` 放入 `X-CSRF-Token` 请求头。开发时优先使用同源代理。
- 普通分页为 `limit=20`（1–100）、`offset=0`，返回 `{"items":[],"total":0,"limit":20,"offset":0}`；arXiv 搜索和任务事件例外。
- 错误为 `{"error":{"code":"…","message":"…","details":{}}}`，响应头 `X-Request-ID` 用于查日志。会话无效为 401，Origin/CSRF 无效为 403，参数无效为 422；429 若附 `Retry-After`，按其等待。
- 根路径 `GET /health` 返回 `{"status":"ok"}`；`GET /ready` 校验数据库连接和迁移版本，就绪返回 `{"status":"ready"}`，否则为 503。

## 2. 账号与会话

账号 POST 使用 JSON 并校验 Origin。用户名为 3–32 个 ASCII 字母、数字或下划线，禁止保留名；密码为 6–128 字符。用户名忽略大小写查重，登录须匹配注册时大小写；邮箱验证后才可登录。

| 方法与路径 | JSON 输入 | 成功结果 |
| --- | --- | --- |
| `POST /auth/register` | `username, email, password` | 202，受理注册与验证邮件 |
| `POST /auth/verify-email` | `token, password`（注册密码） | 200，完成验证 |
| `POST /auth/resend-verification`、`POST /auth/forgot-password` | `email` | 202，通用受理响应 |
| `POST /auth/login` | `username, password` | 200，设置 Cookie，返回 `user, csrf_token` |
| `GET /auth/me` | — | 200，返回 `user, csrf_token` |
| `POST /auth/logout` | `{}` | 200，撤销当前会话 |
| `POST /auth/reset-password` | `token, password`（新密码） | 200，撤销全部会话 |
| `POST /auth/change-password` | `current_password, password` | 200，保留当前会话、撤销其余会话 |

`logout/change-password` 需要会话和 CSRF。注册、重发验证、找回密码还需邮件配置，缺失为 `503 AUTH_UNAVAILABLE`；202 不代表已投递，Mail Worker 负责发送，语言由 `Accept-Language` 选择，默认英文。[账号实现](../backend/src/app/auth/api.py)

<a id="13-v3-统一研究接口2026-11-20"></a>

## 3. 网页研究

### 提交

`POST /api/v1/agent-research`，示例：

```json
{"question":"比较论文库中 Transformer 相关论文的方法与局限，并引用原文。","paper_ids":[],"allow_search":true}
```

- `question` 非空、最多 8000 字符。`paper_ids` 默认空，最多 20 个不重复的本账号论文 UUID，保留顺序；允许 `uploaded/processing/ready` 原件，解析失败为 `409 PAPER_NOT_READY`。
- `allow_search` 默认 `true`，允许补充库内或外部论文；为 `false` 时至少预选一篇。预算创建时冻结，不接受客户端自定预算。[预算与超时](../backend/README.md#限额与超时)
- 可选 `research`：`model_provider=bailian|tacc|custom`（默认 `bailian`）、`workflow=baseline|extension`（默认 `baseline`）、`context_policy=full|compact`（默认 `full`）、`context_finalize_ratio`（默认 0.9，范围 `(0,1]` 或 null）。`planner/reflection` 默认 false，仅在 Extension 启用；当前网页默认课程模型与 `compact`。
- `tacc/custom` 均需 `tcloud`；课程模型须已就绪。`custom` 使用 `endpoint_url` 或当前用户保存地址，限 `http://<10.0.0.0/16内IP>:8000/v1`；缺地址或未就绪为 `409 MODEL_UNAVAILABLE`，传输不符为 `409 TCLOUD_DISABLED`。
- 可选 `Idempotency-Key` 为 1–128 个无空白的可见 ASCII 字符。同账号同键同输入复用任务；问题、论文顺序、搜索开关或研究配置变化后沿用同键，为 `409 IDEMPOTENCY_CONFLICT`。
- 创建和重放均为 202、`{"task_id":"<uuid>","status":"queued"}`（重放为当前状态）；`Location` 指向详情，`Idempotency-Replayed` 标记重放。调度关闭为 `503 AGENT_NOT_CONNECTED`，传输配置不完整为 `503 RUNNER_NOT_CONFIGURED`。

`USER_ACTIVE_TASKS/USER_DAILY_TASKS` 限制每用户活跃任务和每日新建次数，超限为 429。每日按 UTC 统计现存任务，幂等重放不另计；全站派发并发另行控制。

### 列表、结果和删除

| 方法与路径 | 说明 |
| --- | --- |
| `GET /agent-research/queue/concurrency` | 全站并发 `concurrency`，默认 2。 |
| `PUT /agent-research/queue/concurrency` | `{"concurrency":2}`，范围 1–4，所有用户共用；降低上限不终止已派发任务。 |
| `GET /agent-research` | 本账号统一研究记录，可按 `status` 过滤；项含 `id, question, status, paper_ids, papers, created_at`。 |
| `GET /agent-research/{task_id}` | `task_id, question, status, paper_ids, result, error, metrics`；研究 `queued/running` 或评分 `pending/running` 时继续轮询。 |
| `DELETE /agent-research/{task_id}` | 204，保留 PDF。运行中或已启动后重排为 `409 TASK_RUNNING`；失败但未确认远端停止为 `409 AGENT_STOP_PENDING`。 |

状态为 `queued/running/succeeded/failed`。`result` 交付前为 null，交付后含 `answer, comparison_table, sources, citations, trace, usage, errors, configuration, stop_reason, unresolved`。`completed/partial` 均映射为 `succeeded`，部分完成须展示 `unresolved`；失败查看 `error`，已有原生结果仍可读取。

`paper_ids` 仅含预选论文；`papers` 另含运行中使用的库内论文和打开的 arXiv 来源。库内论文按 UUID 去重，未入库来源为 `id:null`，保留来源标识、版本、标题和 URL；导入匹配版本及摘要后，列表可解析为本地 UUID。

库内引用使用 `local:<paper_uuid>@<sha256>` 和从 1 开始的物理页。后端核验归属、摘要、论文数量和页码后保存关联；外部引用须先导入对应版本，再按本地 UUID 打开原件。[请求/响应模型](../backend/src/app/api/agent_research_schemas.py) · [引用校验](../backend/src/app/agent_bridge/results.py)

## 4. 论文库

| 方法与路径 | 说明 |
| --- | --- |
| `POST /papers` | 单个 `multipart/form-data` 文件字段 `file`，只收 PDF，上限 52,428,800 字节（界面 50 MB）；201 和论文记录，重复上传生成新 ID。 |
| `GET /papers` | 分页及 `status, q`（1–200 字符）过滤；标题和原文件名按不区分大小写的字面子串匹配。 |
| `GET /papers/{paper_id}` | 含 `title, original_filename, status, size_bytes, sha256, page_count, error`；导入件另有 `source`。展示优先使用 `title`。 |
| `GET /papers/{paper_id}/file` | 200，内联返回原始 `application/pdf`。 |
| `DELETE /papers/{paper_id}` | 204，清理 PDF、来源及关联的导入记录；任务关联中为 `409 PAPER_IN_USE`，解析中为 `409 PAPER_PROCESSING`。 |

状态为 `uploaded → processing → ready / failed`。Parser 只解析元数据，最多 500 页，不支持加密 PDF；超页数或解析失败记录在 `error`，不改变上传已受理的事实。文件名或 PDF 头无效为 422，文件超限为 413。arXiv 下载上限相同，反向代理须为 multipart 留余量。[论文接口](../backend/src/app/api/papers.py)

### 4.1 Agent 论文库

Worker 签发的只读 Bearer 绑定派发、用户、搜索权限和截止时间，任务终结、过期或账号停用即失效。CLI 调试也可签发会话绑定令牌，最长 30 分钟。[客户端](../agent/apis/library.py)

| 方法与路径 | 鉴权与参数 |
| --- | --- |
| `POST /agent/library-token` | Cookie、Origin、CSRF，无请求体；返回 `access_token, token_type, expires_at`。 |
| `GET /agent/papers` | Bearer；分页、`status, q`；按空白分词，不区分大小写，`match=all`（默认）或 `any`。 |
| `GET /agent/papers/{paper_id}/pdf` | Bearer；流式原件。客户端组合 `download_url` 与后端地址，并核验 `size_bytes, sha256`。 |
| `GET /agent/search-arxiv` | 仅获准搜索的活动作业；`q` 为 1–400 字符，`limit` 默认 5、范围 1–5；后端用 Tavily 代理搜索 arXiv，密钥不下发。 |

失效令牌为 `401 AGENT_LIBRARY_TOKEN_REQUIRED`；越权论文为 `404 PAPER_NOT_FOUND`；禁搜作业查列表为 `403 AGENT_LIBRARY_SEARCH_DISABLED`，仍可读预选原件；外部检索未授权为 `403 AGENT_SEARCH_DISABLED`、未配置为 `503 TAVILY_NOT_CONFIGURED`、上游失败为 `502 TAVILY_SEARCH_FAILED`。

`app.main:create_library_app` 仅挂载上述三个 GET 和 `/health`，不提供登录、研究提交或令牌签发。

## 5. arXiv 搜索与导入

| 方法与路径 | 说明 |
| --- | --- |
| `GET /paper-search` | `q` 为 1–200 字符、最多 20 词；`limit=10`（最大 50）、`offset=0`（最大 1000）；`sort_by=relevance/submittedDate/lastUpdatedDate`、`sort_order=ascending/descending`。结果附用户导入状态。 |
| `POST /paper-imports` | 如 `{"provider":"arxiv","external_id":"1706.03762v7"}`，按用户和来源版本创建或复用；排队/执行中为 202，已有终态为 200。 |
| `GET /paper-imports`、`GET /paper-imports/{import_id}` | 列表或详情，列表可按 `status` 过滤；成功后用 `paper_id` 查询独立解析状态。 |
| `POST /paper-imports/{import_id}/retry` | `{"expected_attempt":1}`，重试失败下载；重复调用复用下一轮，冲突为 `409 IMPORT_RETRY_CONFLICT`。 |

状态为 `queued/running/succeeded/failed`，下载成功不等于解析成功。网页搜索、创建和重试需 `ARXIV_ENABLED/ARXIV_CONTACT_EMAIL`，否则为 `503 ARXIV_NOT_CONFIGURED`；读取已有记录不受开关影响。Import Worker 下载，Parser 解析；`USER_ACTIVE_IMPORTS` 限制活跃导入数。Agent Tavily 搜索与此配置独立。[导入接口](../backend/src/app/api/imports.py)

## 6. 任务兼容接口与平台诊断

`/tasks` 保留历史客户端和运维视图，也可查询统一研究任务的作业号。

| 方法与路径 | 说明 |
| --- | --- |
| `POST /tasks` | `task_type, question, paper_ids, workflow_type, budget`；仅 `baseline`，summary/qa 选 1 篇，review 选 2–20 篇，qa/review 必填问题。关闭搜索，由同一 Agent 派发，兼容 `budget` 不覆盖后端预算；202，标识字段为 `id`。 |
| `GET /tasks` | 分页及 `status, task_type, workflow_type, is_mock` 过滤。 |
| `GET /tasks/{task_id}` | 阶段、用量、错误、`metrics` 及 `agent.dispatch_id/remote_job_id`；课程传输为 `tcloud-v1`。 |
| `GET /tasks/{task_id}/agent-result` | 原生结果和输入摘要；未交付为 `result:null`，无 Agent 记录为 `404 AGENT_RESULT_NOT_FOUND`。 |
| `GET /tasks/{task_id}/events` | `after_seq=0`、`limit=100`（最大 500），返回 `items, next_after_seq, has_more`。 |
| `GET /tasks/{task_id}/artifacts` | 旧产物视图，含 Markdown 和库内引用；未成功为 `{"items":[]}`。 |
| `DELETE /tasks/{task_id}` | 删除规则同统一研究接口。 |

<a id="agent-dispatch-protocol"></a>

## 7. Agent 派发协议

1. API 校验配额、论文归属，冻结来源、预算和配置，创建 `task_id/dispatch_id`。
2. Worker 在 `AGENT_EXCHANGE_ROOT/outbox/<dispatch_id>/` 写入 `input.zip`，另写私有 `library-access.json`。`tcloud` 包含 `manifest.json/task.json/sources.json`，预选 PDF 从后端下载。
3. `tcloud submit` 派发课程作业，`tacc/research/run_job.py` 运行独立 Agent，完成原文提取、分块、模型调用和证据生成。
4. 作业在 `$TACC_USERDIR/acs-research/jobs/<dispatch_id>/` 原子发布 `status.json/result.json`，Worker 校验后入库。

状态信封为 `agent-job-status-v1`，结果信封为 `agent-result-v1`，后者含 `dispatch_id, input_sha256, remote_job_id, result`。摘要取 ZIP 内 `manifest.json` 原始字节的 SHA-256；还须核验任务身份、库内来源及页码。[契约](../backend/src/app/agent_bridge/contracts.py) · [校验与入库](../backend/src/app/agent_bridge/store.py)

`AGENT_LIBRARY_PUBLIC_URL` 须为计算节点可达的 HTTPS 来源。百炼可用 Worker 私有 `AGENT_TCLOUD_MODEL_ENV_FILE` 签发单作业临时凭据；课程模型用 TACC 内网地址。期限从首次领取开始，含打包、远端排队和执行；恢复沿用原标识与截止时间，回执不明时保留现场。离队不等于结果已入库。

`manual/local/tacc` 兼容传输共用结果格式，输入 ZIP 另带 `papers/<UUID>.pdf`，入口单独配置。[传输与预算](../backend/README.md#agent-dispatch) · [集群操作](../tacc/TACC.md)

## 8. 任务指标与评分

两种任务详情均返回 `metrics.schema_version=task-metrics-v1`，列表不含指标：

| 分组 | 内容 |
| --- | --- |
| `metrics.evaluation` | 状态、版本、综合分和五维 `score/reason`：事实与证据一致性、引用支持、完成度、分析质量、清晰度。每维 0–5，权重依次 30/30/20/15/5%，综合分 0–100。 |
| `metrics.agent` | 步数、模型/工具调用数、输入/输出/总 Token 及完整性。 |
| `metrics.model_server` | TTFT、TPOT/mean ITL（ms）、输出 Token/s、缓存命中/查询 Token、命中率及 GPU 快照。聚合含样本数、来源，缺失为 null。 |

GET 只读已存数据；性能仅对来源口径一致的调用样本取算术均值，缓存命中率按可用命中/查询 Token 求比（0–1），GPU 为完成时共享设备快照。缺失或证据不足不显示成零。[完整字段与口径](../backend/README.md#任务指标与前端接入)

启用评分后，新交付结果自动入队，历史结果不补扫；已回传但无可用产物的失败结果记为 `skipped/NO_USABLE_RESULT`。评分失败不改变研究正文，需独立轮询。

| 方法与路径 | 说明 |
| --- | --- |
| `GET /tasks/{task_id}/evaluation` | 最新版本及完整报告，无记录为 `not_requested`；加 `?evaluation_id=<UUID>` 固定读取历史版本。 |
| `POST /tasks/{task_id}/evaluation` | 无请求体，需会话、Origin、CSRF；202，申请、复用或在尝试上限内重试。须启用评分并运行评分 Worker。 |

报告版本字段为 `id`，详情摘要为 `evaluation_id`；状态为 `not_requested/pending/running/succeeded/failed/skipped`。成功还须按 `report.assessment=scored|insufficient_evidence` 区分是否可评分。相同输入与配置复用版本；每用户每 UTC 日新版本额度由 `EVALUATION_DAILY_LIMIT` 控制，复用/重试已预留版本不重复计数。

常见错误：404 任务/版本不存在，409 结果未终结或尝试耗尽，429 新版本额度已满，503 未配置。评分包含返回摘录和可读取的库内被引页；原文处理、模型请求分别有超时，不限制被引页数。[评分与限制](../backend/README.md#deepseek-evaluation) · [接口实现](../backend/src/app/api/evaluations.py)

## 9. 模型服务

| 方法与路径 | 说明 |
| --- | --- |
| `GET /models` | 课程服务状态、`generation`、作业号、地址、是否为启动者、用户保存地址及百炼配置状态，不返回密钥。 |
| `POST /models/tacc/start` | 202，申请启动课程模型，须启用 `tcloud` 并运行研究 Worker；受理不等于就绪。 |
| `POST /models/tacc/stop?generation=<UUID>` | 202，停止活动轮次仅限启动者；轮次变化为 409，非启动者为 403。 |
| `PUT /models/shared` | `{"base_url":"http://10.0.3.11:8000/v1"}`，保存用户课程内网地址，范围同 `custom`。 |
| `DELETE /models/shared` | 204，删除用户保存地址。 |

写请求需会话、Origin、CSRF；课程调度关闭时 start/stop 为 `409 TCLOUD_DISABLED`。[模型服务实现](../backend/src/app/api/model_services.py)
