# 前后端 API 契约

网页使用 `/api/v1/agent-research` 创建和查看研究，TACC 作业使用 `/api/v1/agent/papers` 检索和读取用户论文库。路由及已声明的请求、响应模型可在主 API 的 `/docs` 或 `/openapi.json` 查看。[运行与验收](../tacc/TACC.md) · [后端与 Agent 派发协议](agent-backend-integration.md)

## 1. 请求与响应

- 业务接口前缀为 `/api/v1`。下文表格中省略该前缀。资源 ID 使用 UUID；客户端按当前登录账号访问资源，跨账号查询返回 404。
- 浏览器通过 HttpOnly Cookie 携带会话。已登录用户的业务写请求需要与 `FRONTEND_PUBLIC_URL` 匹配的 `Origin` 及当前 `X-CSRF-Token`。Agent 只读接口的 Bearer 鉴权见第 4.1 节。
- 普通列表接受 `limit`（默认 20，范围 1–100）和 `offset`（默认 0），响应为 `{"items":[],"total":0,"limit":20,"offset":0}`。arXiv 搜索与任务事件各有自己的分页规则。
- 错误响应为 `{"error":{"code":"…","message":"…","details":{}}}`，可用响应头 `X-Request-ID` 查日志。会话失效返回 401，Origin 或 CSRF 无效返回 403，参数校验失败返回 422；遇到 429 时按 `Retry-After` 指示等待。
- `GET /health` 返回 `{"status":"ok"}`；`GET /ready` 在数据库连接及 Alembic 版本均就绪时返回 `{"status":"ready"}`，否则返回 503。这两个路径位于根目录。

## 2. 账号与会话

账号路径以 `/api/v1/auth` 开头。所有账号 POST 使用 JSON，并校验浏览器 Origin。注册时用户名为 3–32 个 ASCII 字母、数字或下划线（保留名除外），密码为 6–128 个字符；验证邮箱后用注册时大小写一致的用户名登录。注册、重发验证邮件和找回密码需要邮件配置，缺失时返回 `503 AUTH_UNAVAILABLE`。

| 方法与路径 | JSON 输入 | 成功结果 |
| --- | --- | --- |
| `POST /auth/register` | `username, email, password` | 202，受理注册与验证邮件 |
| `POST /auth/verify-email` | `token, password`（注册时的密码） | 200，验证后可登录 |
| `POST /auth/resend-verification`、`POST /auth/forgot-password` | `email` | 202，返回通用受理响应 |
| `POST /auth/login` | `username, password` | 200，设置 Cookie，返回 `user` 和 `csrf_token` |
| `GET /auth/me` | — | 200，返回当前 `user` 和 `csrf_token` |
| `POST /auth/logout` | `{}` | 200，撤销当前会话 |
| `POST /auth/reset-password` | `token, password`（新密码） | 200，撤销全部会话 |
| `POST /auth/change-password` | `current_password, password` | 200，保留当前会话，撤销其他会话 |

`logout` 和 `change-password` 需要当前会话和 CSRF。重发验证、找回密码的 202 表示请求已受理，投递由 Mail Worker 执行。[账号实现](../backend/src/app/auth/api.py)

<a id="13-v3-统一研究接口2026-11-20"></a>

## 3. 网页研究

### 提交

`POST /api/v1/agent-research`，以当前用户身份提交。例如，以下问题会让 Agent 自行检索论文库：

```json
{"question":"请在我的论文库找到 Orchid Calibration Report，引用第二页的最终校验标签。","paper_ids":[],"allow_search":true}
```

- `question` 必填，非空，最多 8000 字符。`paper_ids` 默认为空数组，最多 20 个不重复的本账号论文 UUID，按提交顺序保存。允许使用 `uploaded`、`processing`、`ready` 的原件；已解析失败的预选论文返回 `409 PAPER_NOT_READY`。
- `allow_search` 默认为 `true`，允许 Agent 按需补充来源，包括本账号的论文；设为 `false` 时至少预选一篇，仅使用指定论文。执行预算由后端在创建时确定。
- 可选请求头 `Idempotency-Key` 为 1–128 个不含空白的可见 ASCII 字符。同账号同键同输入返回原任务；更换问题、论文顺序或搜索开关却沿用同键，返回 `409 IDEMPOTENCY_CONFLICT`。
- 首次创建返回 `202` 和 `{"task_id":"<uuid>","status":"queued"}`。幂等重放同样返回 202，`task_id` 保持一致，`status` 为该任务当前状态。响应头 `Location` 指向详情接口，`Idempotency-Replayed` 标记是否重放。派发未启用返回 `503 AGENT_NOT_CONNECTED`，传输配置不完整返回 `503 RUNNER_NOT_CONFIGURED`。

### 列表、结果和删除

| 方法与路径 | 说明 |
| --- | --- |
| `GET /agent-research` | 本账号通过统一研究接口创建的记录，可按 `status` 过滤。列表项含 `id, question, status, paper_ids, papers, created_at`。 |
| `GET /agent-research/{task_id}` | 返回 `task_id, question, status, paper_ids, result, error`。网页在 `queued`、`running` 时轮询，`succeeded` 或 `failed` 后停止。 |
| `DELETE /agent-research/{task_id}` | 成功返回 204。运行中或已开始后重新排队的任务返回 `409 TASK_RUNNING`。失败且仍待确认远端停止的作业返回 `409 AGENT_STOP_PENDING`。原 PDF 保留在论文库。 |

`paper_ids` 始终表示提交时的预选论文。第一次请求可以为空；运行中发现的论文出现在 `result.sources`。后端按用户归属、UUID、SHA-256、论文数量以及所引物理页校验库内检索结果，再保存任务关联。

`result` 在交付前为 `null`。交付后包含 `answer`、`comparison_table`、`sources`、`citations`、`trace`、`usage`、`errors`、`configuration`、`stop_reason` 和 `unresolved`。`completed` 和 `partial` 对应 `status=succeeded`，部分完成时应同时展示未解决项。失败时查看 `error`；如 Agent 已交付失败结果，仍可读取 `result`。

库内引用使用 `local:<paper_uuid>@<sha256>` 的来源标识和从 1 开始的物理页码。网页按论文 UUID 打开原件对应页。外部 arXiv 来源保留其标识与版本；用户确认导入该版本并完成解析后，网页使用本地论文 UUID 打开引用。[研究请求与响应模型](../backend/src/app/api/agent_research_schemas.py) · [结果校验](../backend/src/app/agent_bridge/results.py)

## 4. 论文库

| 方法与路径 | 说明 |
| --- | --- |
| `POST /papers` | `multipart/form-data` 的 `file` 字段，限单个 PDF，最大 52,428,800 字节。返回 201 和论文记录；相同文件重复上传会获得新的 ID。 |
| `GET /papers` | 分页列表，可按 `status` 或 `q`（1–200 字符）过滤。`q` 在标题和原文件名中匹配不区分大小写的字面子串。 |
| `GET /papers/{paper_id}` | 元数据含 `title, original_filename, status, size_bytes, sha256, page_count`，arXiv 导入件另有 `source`。 |
| `GET /papers/{paper_id}/file` | 200，内联返回原始 `application/pdf`。 |
| `DELETE /papers/{paper_id}` | 204。仍有关联任务时返回 `409 PAPER_IN_USE`，正在解析返回 `409 PAPER_PROCESSING`。 |

上传后状态依次为 `uploaded → processing → ready / failed`。Parser 提取标题、页数等元数据；Agent 执行研究时自行读取原件。文件名或 PDF 头无效返回 422，超限返回 413。

### 4.1 Agent 论文库

TACC 作业使用 Worker 自动签发的只读令牌。后端按 `dispatch_id` 核对账号、授权范围及截止时间。任务终结、过期或账号停用后，令牌随即失效。独立 CLI 调试时，也可从主 API 签发绑定当前浏览器会话的令牌，最长 30 分钟。[作业授权与配置](../tacc/TACC.md) · [Agent 客户端](../agent/apis/library.py)

| 方法与路径 | 鉴权与参数 |
| --- | --- |
| `POST /agent/library-token` | 浏览器 Cookie、Origin、CSRF，无需请求体。返回 `access_token, token_type, expires_at`。 |
| `GET /agent/papers` | `Authorization: Bearer <token>`。支持分页、`status` 和 `q`；关键词按空白拆分，在标题和原文件名中匹配，`match=all` 为默认，`match=any` 表示命中任一词。 |
| `GET /agent/papers/{paper_id}/pdf` | 同一 Bearer，流式返回原件。客户端将检索结果的 `download_url` 与后端地址组合，用 `size_bytes` 和 `sha256` 核验内容。 |

缺失或失效令牌返回 `401 AGENT_LIBRARY_TOKEN_REQUIRED`。关闭搜索的作业查列表返回 `403 AGENT_LIBRARY_SEARCH_DISABLED`，仅可下载预选论文。超出授权或不存在的论文返回 `404 PAPER_NOT_FOUND`。用于隧道的独立只读入口只挂载两个 GET 和 `/health`。

## 5. arXiv 搜索与导入

| 方法与路径 | 说明 |
| --- | --- |
| `GET /paper-search` | 必填 `q`（1–200 字符，最多 20 个词）；`limit` 默认 10、最大 50，`offset` 为 0–1000。支持 `sort_by=relevance/submittedDate/lastUpdatedDate`、`sort_order=ascending/descending`。每条结果附当前用户的导入状态。 |
| `POST /paper-imports` | 例如 `{"provider":"arxiv","external_id":"1706.03762v7"}`。按用户、来源和明确版本创建或复用，排队或执行中返回 202，已有终态返回 200。 |
| `GET /paper-imports`、`GET /paper-imports/{import_id}` | 查看列表或单条导入。列表支持按 `status` 筛选。成功后用 `paper_id` 查询论文的独立解析状态。 |
| `POST /paper-imports/{import_id}/retry` | 传 `{"expected_attempt":1}` 重试一次失败的下载。重复请求返回已产生的下一次尝试，版本冲突返回 `409 IMPORT_RETRY_CONFLICT`。 |

网页搜索、创建导入和失败重试需要后端配置 `ARXIV_ENABLED` 和 `ARXIV_CONTACT_EMAIL`；未配置返回 `503 ARXIV_NOT_CONFIGURED`。下载由 Import Worker 执行，解析由 Parser Worker 执行。读取已有导入记录和 PDF 可独立进行。[搜索与导入接口](../backend/src/app/api/imports.py)

## 6. 任务兼容接口与平台诊断

`/api/v1/tasks` 继续提供已有客户端和运维工具使用的视图。网页研究任务也能通过其详情查询平台作业号。

| 方法与路径 | 说明 |
| --- | --- |
| `POST /tasks` | 接受 `task_type, question, paper_ids, workflow_type, budget`。仅开放 `baseline`。summary/qa 选 1 篇，review 选 2–20 篇；qa/review 必填问题。该入口关闭搜索，由同一个 Agent Worker 派发，合法的兼容 `budget` 不覆盖后端限额。成功返回 202，任务标识字段为 `id`。 |
| `GET /tasks` | 支持分页及 `status, task_type, workflow_type, is_mock` 过滤，可查询历史任务。 |
| `GET /tasks/{task_id}` | 包含阶段、资源使用和错误信息。Agent 任务的 `agent.dispatch_id` 对应派发，`agent.remote_job_id` 是平台回执中的作业号，课程 SDK 的 `agent.transport` 为 `tcloud-v1`。 |
| `GET /tasks/{task_id}/agent-result` | 返回原生 Agent 结果及输入摘要，尚未交付时 `result=null`。没有 Agent 记录时返回 `404 AGENT_RESULT_NOT_FOUND`。 |
| `GET /tasks/{task_id}/events` | 增量事件，`after_seq` 默认 0，`limit` 默认 100、最大 500，返回 `items, next_after_seq, has_more`。 |
| `GET /tasks/{task_id}/artifacts` | 旧产物视图，含 Markdown 和库内引用；任务尚未成功时返回 `{"items":[]}`。 |
| `DELETE /tasks/{task_id}` | 删除任务记录，运行中及待确认远端停止的任务沿用研究接口的删除规则。 |
