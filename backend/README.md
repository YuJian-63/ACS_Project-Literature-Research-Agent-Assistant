# 后端开发

> 2026-11-21：后端仅通过独立 Agent 执行新研究任务。内置 LangGraph、Mock 及后端文本分块/检索/生成流程已删除；历史数据库结构、任务结果和引用保留。本次清理不新增迁移，也不删除历史数据。

后端负责账号与权限、论文元数据与 PDF 持久化、arXiv 搜索导入、研究派发、结果存储与查询。Agent 负责 PDF 文本提取、分块、检索、摘要、问答和综述。统一研究入口为 `/api/v1/agent-research`，旧 `/api/v1/tasks` 创建入口也只派发给 Agent。两者共享用户配额和幂等规则。账号配置见第 10 节；接口与 Agent 协议分别见 `../docs/api-contract.md`、`../docs/agent-backend-integration.md`，其中旧研究执行器的历史说明不再代表当前后端实现。

## 1. 首次启动

需要 Python 3.11+、uv、PostgreSQL。可使用 Docker Compose 启动开发数据库。首次创建配置；已有 `.env` 时不要覆盖。以下命令从项目根目录开始：

```powershell
cd backend
uv sync --locked
Copy-Item .env.example .env
docker compose up -d --wait postgres
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Linux/macOS 将复制命令替换为 `cp .env.example .env`。已有旧数据库先备份并检查迁移要求，尤其是拒绝非空匿名业务库升级的 `20261114_0004`，见第 10 节。当前迁移 head 为 `20261121_0008`；本次 Agent-only 清理不改变迁移图或 schema。

分别打开终端，在 `backend` 目录运行所需进程：

```powershell
uv run --locked python -m app.parser_worker
uv run --locked python -m app.mail_worker
uv run --locked python -m app.runner_worker
```

Parser 只提取 PDF 元数据。邮件 Worker 需要完整 SMTP 配置。研究 Worker 需要 `TASK_RUNNER=agent`、`AGENT_DISPATCH_ENABLED=true` 和有效传输配置，见第 8 节；未启用派发时，API 仍可提供账号/论文等服务，但创建研究返回 503，不会回退到其他执行器。按需开启 arXiv 后再运行 `python -m app.import_worker`。所有进程必须使用相同数据库和 `STORAGE_ROOT`。原 Mock 入口 `app.worker` 已删除，旧部署应停止该进程。

`/health` 检查 API 存活，`/ready` 检查数据库连接及迁移版本；两者不证明邮件投递、Agent 或 TACC 已连通。`/docs` 和 `/openapi.json` 提供运行中接口文档。API 不自动建表或执行迁移，不依赖请求进程中的后台任务执行研究。

依赖由 `uv.lock` 固定，已移除 LangGraph 及其孤立传递依赖。Agent 的 Python 环境和模型配置独立管理；安装后端不会安装 Agent。公共索引配置见 `pyproject.toml`，切换镜像时应核对锁文件与包哈希。

## 2. 数据库配置

`.env.example` 中的密码只是本地开发示例，不是真实凭据。`.env` 已被 `.gitignore` 排除。PostgreSQL 端口仅发布到本机 `127.0.0.1`，不是公开部署配置。

| 变量 | 用途 |
| --- | --- |
| DATABASE_URL | Python 应用和 Alembic 的连接地址；必填 |
| POSTGRES_DB | Compose 首次初始化的数据库名 |
| POSTGRES_USER | Compose 首次初始化的数据库用户 |
| POSTGRES_PASSWORD | Compose 首次初始化的用户密码 |
| POSTGRES_PORT | 本机端口，示例为 5432 |
| STORAGE_ROOT | 默认 backend/runtime/storage；相对路径始终相对 backend 解析，上传文件使用 uploads/{UUID}.pdf |
| TASK_MONITOR_ENABLED | 默认 true；API 启动时及每 10 秒恢复过期任务，Worker 也运行独立恢复监控 |
| PARSER_TIMEOUT_SECONDS | 默认 120 秒，范围 1—600；限制每份 PDF 的元信息提取子进程时间 |
| TASK_RUNNER | 默认 agent，仅支持独立 Agent |
| AGENT_DISPATCH_ENABLED | 默认 false；完成传输配置后启用 |
| AGENT_TRANSPORT | manual、local 或 tacc |
| AGENT_LIBRARY_PUBLIC_URL | 可选，计算节点可访问的后端 HTTPS 地址。设置后，Worker 在每个派发的 outbox 写入作业私有的 `library-access.json`。课程 CPU 联调见 [TACC 说明](../tacc/TACC.md)。 |
| CORS_ORIGINS | JSON 字符串数组；默认允许 localhost:5173 和 127.0.0.1:5173，不接受逗号分隔的裸字符串 |

应用在宿主机运行，示例 DATABASE_URL 连接 `127.0.0.1:5432`。若已有独立 PostgreSQL 17+，可直接配置其 DATABASE_URL，跳过 Compose。修改用户、密码、端口或数据库名时，必须同步修改 DATABASE_URL；已初始化的数据卷不会因为更改 POSTGRES_* 自动修改已有数据库账号。

配置读取顺序为进程环境变量优先于 `backend/.env`；显式传入 Settings 的字段优先级更高。配置文件路径相对后端目录固定，不依赖启动时的当前目录。Compose 的其他字段会被应用配置忽略。

支持 `postgresql://` 和 `postgresql+psycopg://`，统一使用 psycopg 3；拒绝 SQLite、其他驱动及缺少数据库名的地址。密码包含 `@`、`%`、`#`、`/` 等保留字符时先做 URL 百分号编码，不需要为 Alembic 再将 `%` 写成 `%%`。连接密码应放在 @ 前的 userinfo 中；拒绝 password、sslpassword 查询参数，避免 Engine/URL 默认展示泄露查询参数中的密码。连接地址不经过 INI 插值，Settings 默认展示和配置错误文本会隐藏敏感输入；不要主动输出解密后的配置。

## 3. 代码入口

| 路径 | 职责 |
| --- | --- |
| `src/app/main.py`、`config.py`、`errors.py` | 应用工厂、中间件、共享配置与统一错误 |
| `src/app/api/` | 账号外的 HTTP 路由、公开 DTO 与结果展示 |
| `src/app/auth/`、`mail_worker.py` | 注册/验证/登录/找回、Cookie/CSRF、限流及 SMTP 投递 |
| `src/app/db/` | 数据库连接、账号/论文/任务/Agent 模型及历史结构 |
| `src/app/papers/storage.py` | PDF 上传校验、受控持久化、大小/hash 核对与写入补偿 |
| `src/app/papers/pdf_parser.py`、`lifecycle.py` | 有界元信息提取、页数/标题写入、解析租约与恢复；不创建 chunks |
| `src/app/papers/refresh_titles.py` | 历史上传论文标题预览/补提取，保留原文件和历史证据 |
| `src/app/sources/` | arXiv 客户端、共享访问许可、搜索缓存及持久化导入 |
| `src/app/tasks/` | 提交/查询、幂等、配额、任务领取/心跳/超时/恢复、历史预算兼容 |
| `src/app/agent_bridge/` | Agent 协议、输入包、授权 PDF/论文库访问、local/TACC 传输及结果入库 |
| `src/app/workers/` | Parser、Import Worker 的进程监督与资源释放 |
| `src/app/runner_worker.py` | 转发到 `app.agent_bridge.worker.main`，保留既有研究 Worker 启动命令 |
| `src/app/parser_worker.py`、`import_worker.py` | 元信息解析/来源导入启动入口 |
| `alembic/` | 冻结的历史迁移及 Alembic 环境 |
| `sql/schema.sql` | 空 schema 的设计对照；不与迁移在同一数据库重复执行 |

`research/`、后端模型客户端、后端证据检索/生成校验及 Mock Worker 已删除。内部调用应使用现有 `tasks`、`papers` 或 `agent_bridge` 模块。

模块导入不连接数据库或自动建表。调用方显式创建 Engine；数据库使用 READ COMMITTED 和 UTC。短事务使用 `Session.begin()`，进程退出时释放 Engine：

```python
from sqlalchemy import text
from app.config import Settings
from app.db.session import create_database_engine, create_session_factory

engine = create_database_engine(Settings())
sessions = create_session_factory(engine)
try:
    with sessions.begin() as session:
        result = session.scalar(text("SELECT 1"))
finally:
    engine.dispose()
```

数据库默认值在 INSERT/flush 后产生；构造模型时不能假设 id、status 或 created_at 已填充。更新时显式维护 updated_at。JSONB 内容使用整体重新赋值；可空 JSONB 字段的 Python None 对应 SQL NULL。

## 4. 迁移维护

初始迁移包含冻结 SQL，不在执行时读取 schema.sql 或当前 ORM。日后修改模型后创建新迁移，保留历史 revision：

```powershell
uv run --locked alembic revision --autogenerate -m "describe schema change"
uv run --locked alembic upgrade head
uv run --locked alembic check
```

自动生成后需人工检查 CHECK、复合外键、删除行为、默认值及索引；不能只依赖 `alembic check`。不要在服务启动时调用 metadata.create_all，也不要在已运行初始迁移的数据库再执行 sql/schema.sql。

无需数据库或 DATABASE_URL 即可预览初始升级 SQL：

```powershell
uv run --locked alembic upgrade head --sql
uv run --locked alembic downgrade 20261110_0001:base --sql
```

`20261114_0004` 明确拒绝降级，不能恢复匿名共享访问；需要回退时只能按已核验的升级前备份恢复。旧 revision 的 downgrade 可删除业务表及数据，来源迁移也有拒绝非空降级保护；这些历史能力不能作为绕过 0004 保护的方式。停止本地数据库可执行 `docker compose down`，该命令保留命名数据卷。

## 5. 验证与边界

在 `backend` 目录执行普通回归：

```powershell
uv run --locked python -B -m unittest discover -s tests -v
```

`test_agent_only.py` 验证退役执行器不能配置/领取、后端不再导入 LangGraph、元信息解析不返回 chunks，以及无可提取文本和标题提取失败时的行为。`test_pdf_limits.py` 保留 50 MB 文件和真实解析子进程边界检查。

数据库回归需单独创建可销毁的 loopback PostgreSQL 测试库，设置以下环境变量；不要指向开发、验收或生产业务库。测试会清空专用库的业务表或创建并删除独立 schema：

| 变量 | 数据库名约束 |
| --- | --- |
| `OWNERSHIP_TEST_DATABASE_URL` | `ownership_tests_<32位小写十六进制>` |
| `AGENT_TEST_DATABASE_URL` | `agent_bridge_tests_<32位小写十六进制>` |
| `AGENT_MERGE_TEST_DATABASE_URL` | `agent_merge_tests_<32位小写十六进制>` |
| `AUTH_TEST_DATABASE_URL` | `auth_tests_<32位小写十六进制>` |

覆盖用户隔离、幂等/配额、PDF 元信息写入、历史 chunks 保留、原生 Agent 引用、同一 dispatch 恢复、过期执行器清退及迁移无漂移。没有测试库时相关测试明确跳过；跳过不等于验证成功。完整结果与现存阻塞记录见 `plans/2026-11-21-agent-only.md`。真实模型、浏览器和 TACC 的远程验收需另行执行，不能由离线回归推定通过。

## 6. 最小业务闭环

1. 配置账号/邮件，启动 API 与邮件 Worker；注册、验证邮箱并使用原大小写用户名登录。
2. 上传 PDF，Parser 提取标题与页数；或开启 arXiv 后通过 Import Worker 持久化论文 PDF。
3. 配置并启动 Agent Worker，通过统一研究入口提交问题，按需选择论文和允许搜索。旧 `/api/v1/tasks` 的 summary/qa 选择一篇，review 选择 2—20 篇；extended 仍返回 `WORKFLOW_NOT_AVAILABLE`。
4. 查询任务详情、events 和 artifacts；`/api/v1/tasks/{task_id}/agent-result` 保留原生 Agent 结果。核对正文、引用页码及证据来源。
5. 刷新或重启 API 后用 task_id 恢复；退出登录后停止私有请求，另一个账号不能读取原论文、PDF 或研究。

手动 HTTP 客户端需可信 Origin、登录 Cookie、返回的 csrf_token；写操作额外携带 Origin 和 X-CSRF-Token。任务提交使用 Idempotency-Key，网络重试复用同一键，主动重跑使用新键。`/docs` 的 API origin 不自动满足可信前端 Origin。不要将密码、Cookie 或令牌写入命令历史。

Agent 可直接使用 uploaded/processing/ready 的 PDF，无需等后端生成文本块；无文件、内容 hash 不符或权限失败仍会拒绝。进入终态前轮询，终态后停止。`partial` 的 Agent 结果保留未解决事项，不能等同于完整研究。

## 7. 运行边界与恢复

- 上传与 arXiv PDF 导入统一限制为 50 MB（52,428,800 字节）。以实际流量统计并计算 SHA-256，不只信任 Content-Length；下载保持受控 URL/TLS 和超时限制。
- Parser 在受监督子进程中检查 PDF 文件头、源文件大小/hash、加密状态及页数（最多 500 页），读取元数据标题；必要时仅尝试首面标题。保留子进程超时和结果大小限制，不提取全篇文本，不写入 `paper_chunks`，不提供 OCR。
- `ready` 仅表示后端文件/元信息检查成功，不保证 Agent 能读取正文。扫描件或空白 PDF 可交给 Agent 判断；无法获得标题时保留文件名回退，不影响 PDF 下载。
- 论文元数据更新与 ready 状态原子提交。已验证 arXiv 标题和用户自定义标题不被覆盖；历史文本块和引用不会因元信息处理而重建或删除。
- Agent Worker 使用任务租约与心跳；Worker 重启后继续同一 dispatch/job，保留原 started_at 和截止时间。过期所有者不能覆盖已接管任务。
- 任务超过原始期限以 `TASK_TIMEOUT` 终止。退役 mock/langgraph 的 queued/running 任务由监控标记 `RUNNER_RETIRED`，需用户重新提交给 Agent；终态历史任务、产物和引用继续可读。
- 数据库提交、远程作业回收和结果入库继续遵守原 Agent 协议；未确认停止的远端作业不能通过删除任务绕过保护。
- 公开部署使用 HTTPS、Secure Cookie、可信前端 Origin/CORS，反向代理上传限制至少覆盖 50 MB 文件及 multipart 开销。API 默认绑定 127.0.0.1，数据库不应直接公网暴露。

## 8. 独立 Agent 配置

后端只支持 `TASK_RUNNER=agent`；`mock`、`langgraph` 将导致配置校验失败。更新旧部署前，将该值改为 agent，并停掉旧 Mock/真实本地研究进程。配置传输并验证后再启用 `AGENT_DISPATCH_ENABLED=true`。后端不读取 `LLM_*`、`RESEARCH_*`、`REVIEW_*`、`MOCK_STEP_DELAY_SECONDS` 等旧设置；模型凭据放在 Agent 自己的环境中。

| 传输 | 设置与用途 |
| --- | --- |
| `manual` | 受控文件交换；外部执行端按既有 manifest/result 协议处理 |
| `local` | `AGENT_LOCAL_ROOT`、`AGENT_LOCAL_PYTHON` 指定独立 Agent 根目录和解释器 |
| `tacc` | `AGENT_TACC_HOST`、`AGENT_TACC_HELPER`、`AGENT_TACC_CONFIG` 及可选远程 Python；通过 SSH/Slurm 派发 |

输入包和结果交换位置为 `AGENT_EXCHANGE_ROOT`，为空时使用 `STORAGE_ROOT/agent-exchange`。API/Worker 使用相同路径和传输配置。启动命令仍为 `python -m app.runner_worker`。

Agent 接收原始 PDF 和 manifest 中的来源 ID、标题、大小/hash、可用页数；不依赖后端 chunk ID。结果按现有 `agent-result-v1` 契约验证后保存，原始返回值保留在 `agent_runs`，前端兼容产物/引用仍写入原表。Agent 的 `source_id`、`chunk_id`、`page`、`source_text` 用于来源和证据展示，后端继续验证其结构、来源归属及输入指纹，不把它们转换成后端文本分块。

授权论文库检索 `/api/v1/agent/papers`、库令牌以及 PDF 下载接口保留；全文处理由 Agent 完成。TACC 真实 SSH/Slurm、外网访问和模型服务仍需在目标环境联调。

## 9. arXiv 搜索与导入（MVP-3）

### 开启步骤

1. 启动 Docker Desktop，等引擎就绪。先按第 1 节启动 PostgreSQL；已有数据库先备份，再运行 `uv run --locked alembic upgrade head` 和 `uv run --locked alembic check`，确认 revision 为 `20261114_0003`。不要执行 schema.sql 或删除数据卷。
2. 只在本地 `backend/.env` 设置 `ARXIV_ENABLED=true`，并将 `ARXIV_CONTACT_EMAIL` 填为你自己的有效联系邮箱；不要把邮箱/配置文件提交 Git。首次配置才复制 `.env.example`，不要覆盖现有配置。无需填写任何模型密钥。
3. 重启 API，让它读取新配置。在独立终端启动导入 Worker，另一个终端保持 Parser Worker 运行；所有进程共用 DATABASE_URL 和 STORAGE_ROOT：

```powershell
cd backend
uv run --locked python -m app.import_worker
```

```powershell
cd backend
uv run --locked python -m app.parser_worker
```

4. 打开前端 `/papers/search`，提交一次小范围关键词搜索，选择一个带明确 `vN` 的结果导入。等待「已导入 · 可用于研究」，在论文库核对来源、PDF、页数并进入任务预选。不要连续刷新来源；429 时等倒计时结束再手动操作。Import Worker 未启动时保持「等待导入」，Parser 未启动时保持「已导入 · 正在解析」。
5. 需要研究产物时按第 8 节配置独立 Agent 并运行 Agent Worker。关闭联网只需设 `ARXIV_ENABLED=false`、重启 API 并停止 Import Worker；历史和手动上传不受影响。

### 实现与限制

- 搜索只访问固定官方 HTTPS API；PDF 只允许同版本官方路径和最多 2 次受控重定向，不接收客户端 URL、代理或下载路径。查询最多 200 字符/20 词、每页最多 20 篇、offset 至多 1000。
- 搜索缓存仅保存上游成功元数据，600 秒/100 页；每次查询重新投影本地导入和解析状态。来源关闭或缺少邮箱返回 `503 ARXIV_NOT_CONFIGURED`，读取历史不要求联网配置。
- 搜索来源失败时，API 输出一条安全诊断日志：`request_id`、`phase`、`elapsed_ms`、`code`。阶段仅允许 `connect`、`write`、`pool`、`response_headers`、`response_body`、`deadline`、`source_gate`、`provider_status`、`response_validation`、`unknown`；普通连接失败不进一步推断 TCP/TLS 原因。日志不包含关键词、联系邮箱、原始异常、响应正文或密钥，可用浏览器错误中的请求编号关联。阶段不进入公开错误 envelope。子进程 watchdog 以 124 退出时，父进程明确归类为 `ARXIV_TIMEOUT` / `deadline`。
- API 和所有 Import Worker 共用数据库许可：一次一个来源请求，完成后至少 3 秒，429/503 应用 Retry-After。Worker 首次等待许可受 180 秒总尝试限制；取得许可后元数据预算 20 秒，其中搜索和指定版本元数据的读取等待最多 15 秒，连接/写入/连接池等待最多 5 秒；各阶段均不超过剩余预算，父监督及子进程 watchdog 仍限制整体时长，不自动重试。PDF 含重定向/后续许可等待共用 90 秒，各网络阶段仍最多 5 秒，PDF 最大 50 MB。
- 网络在最小环境的独立子进程运行；父进程可终止超时/取消请求，子进程也有独立总时限 watchdog，避免父进程异常后连接跨越 120 秒许可租约。此为本机 MVP 防护，不是 OS 级内存/CPU/权限沙箱。
- 导入 lease 30 秒/心跳 10 秒；同一版本始终复用一条导入记录。普通 POST 不重试失败，显式重试必须携带 `expected_attempt`；响应丢失后的重放不增加额外 attempt。
- 下载完成才原子发布 Paper(uploaded)、PaperSource 和导入成功，随后由现有解析器独立处理。导入不会生成研究产物/引用，也不按文件 hash 合并手动上传。
- 回滚清理、超时恢复和提交结果核对都通过 Import 行锁/attempt fencing 保护；不确定事务结果时保留最终文件，等待恢复，不删除可能已被成功论文引用的 PDF。不得手工重用 UUID 路径。

### 验收边界

2026-11-12 已在隔离 PGlite 检查旧结构升级、降级保护、三表约束、ORM/迁移/DDL 等价、共享访问许可、缓存、导入 API、Worker/解析器、重试重放和事务/文件补偿。真实子进程测试覆盖大小/安全 URL/超时/停止/父监督缺失；浏览器使用受控夹具验证搜索状态及完整独立进程闭环。

2026-11-13 用户在独立 PostgreSQL 17.6 验收库完成 head 迁移、无结构漂移检查及八组原生多进程/行锁/恢复/共享许可专项验收。随后真实搜索一次、导入 `2512.19700v1`，重复提交复用同一记录且 attempt=1；独立 Import Worker 完成下载，Parser Worker 将本地 PDF 解析为 ready（9 页）。用户同时确认前端历史恢复、来源与本地 PDF 访问、论文预选、Mock 任务成功及结果刷新恢复。上述证据来自用户提供的输出和人工确认，未由代理独立重跑；详细标识与记录见 `../docs/superpowers/plans/2026-11-12-mvp-3-arxiv-search-import.md`。

原生验收覆盖八组专项场景，不代表此前全部 PGlite 故障注入均已在原生环境重跑。真实来源验收仅覆盖一次搜索和一个版本下载，不代表真实上游限流、重定向或故障已被人工触发，也不代表后续超时已恢复。上述 Mock/本地 Runner 属于历史验收，本次已停用；当前执行方式见第 8 节。

## 10. 账号、QQ 邮件与私有数据（2026-11-14）

账号模块已实现 `app.auth.api.router`、五张账号表和 `20261114_0004` 迁移；前端采用用户名/密码登录、强制邮箱验证和邮箱找回。本文记录账号契约与运维要求。主应用已挂载账号路由并启用带凭据 CORS、私有缓存中间件，业务服务已实现归属/配额检查。2026-11-14 本次实施已验证原生所有权/综述 PostgreSQL 检查及完整账号链路通过，证据范围见第 10.3 节。账号接口详见 `../docs/api-contract.md` 第 11 节；表及升级边界详见 `../docs/database-design.md` 第 11 节。

### 10.1 配置与会话

在已有私有环境配置中补齐下表，不要用模板覆盖已有 `.env`。API、邮件 Worker 及相关业务 Worker 应连接同一数据库；API 和邮件 Worker 必须共享账号密钥及邮件加密密钥。账号配置缺失或不安全时返回 `503 AUTH_UNAVAILABLE`，不会回退到匿名业务访问。

| 变量 | 默认值与要求 |
| --- | --- |
| FRONTEND_PUBLIC_URL | `http://127.0.0.1:5173`；唯一可信浏览器 origin，也是邮件链接来源。只能含 HTTP(S) scheme、host、可选端口，路径只能为空或 `/`，不含用户名、查询或 fragment |
| AUTH_COOKIE_SECURE | `false` 仅供 HTTP loopback；公网部署设 `true` 且前端使用 HTTPS |
| AUTH_SESSION_TTL_SECONDS | `604800`（7 天），允许 60—604800 秒 |
| AUTH_VERIFY_TTL_SECONDS | `86400`（24 小时），允许 60—86400 秒；重发仍受注册后 24 小时总窗口约束 |
| AUTH_RESET_TTL_SECONDS | `1800`（30 分钟），允许 60—3600 秒 |
| AUTH_RATE_KEY / AUTH_CSRF_KEY | 各自独立生成、至少 32 UTF-8 字节的随机密钥；分别用于限流标识 HMAC 和会话 CSRF，禁止共用 |
| SMTP_HOST / SMTP_PORT | QQ 默认 `smtp.qq.com:465`，使用验证证书的 SSL/TLS；实现要求端口 465 |
| SMTP_USERNAME / SMTP_FROM | 完整 QQ 发件邮箱地址，两者须相同（比较时忽略大小写） |
| SMTP_AUTH_CODE | QQ 邮箱启用 SMTP 后签发的授权码；不是邮箱登录密码 |
| SMTP_TIMEOUT_SECONDS | `15`，允许 1—60 秒，限制一次投递尝试 |
| MAIL_OUTBOX_KEY | 独立 Fernet 密钥，即 32 随机字节的 URL-safe base64 编码，供 outbox 载荷加解密 |
| USER_ACTIVE_TASKS / USER_ACTIVE_IMPORTS / USER_DAILY_TASKS | 默认 `2 / 2 / 20`；前两者允许 1—100，日任务允许 1—10000；业务服务已实现检查，原生所有权测试已在本次实施验证通过 |

可分别使用 `secrets.token_urlsafe(32)` 生成两个账号密钥、`cryptography.fernet.Fernet.generate_key()` 生成 outbox 密钥，由操作者私下保存到环境或秘密管理器。不要把生成值、Cookie、CSRF、邮件令牌或配置快照写入仓库、截图、日志或实施记录。轮换账号密钥需安排会话/限流影响；队列尚有加密载荷时不能直接替换或丢弃 `MAIL_OUTBOX_KEY`。错误密钥可能使邮件终止并撤销对应令牌，应按受控流程处理后重新申请邮件。

生产 Cookie 名为 `__Host-lra_session`（Secure、HttpOnly、SameSite=Lax、Path=/、无 Domain）；本机 HTTP 使用 `lra_dev_session`（其余属性相同、无 Secure）。浏览器启动先请求 `GET /api/v1/auth/me`，登录及 me 返回 `{user:{id,username,email},csrf_token}`。Cookie 由浏览器保存，CSRF 仅驻留内存。

前端必须使用 `withCredentials: true` / `credentials: "include"`；服务端 CORS 必须允许确切前端 origin、凭据和 `X-CSRF-Token`、`Idempotency-Key`、`Content-Type` 请求头，不能使用 `*`。所有账号 POST 要求 JSON 和匹配 `FRONTEND_PUBLIC_URL` 的 Origin；登录后的业务写入、改密和退出还要求当前会话的 `X-CSRF-Token`，上传 multipart 同样需要。不要在业务输入中增加或信任 `user_id`。

开发时浏览器和 API 统一使用 `127.0.0.1` 或统一使用 `localhost`；端口可以不同，主机名不能混用。即使 CORS 列出两种地址，账号写入仍只信任 `FRONTEND_PUBLIC_URL` 指定的 origin。`/docs` 可浏览接口，但其 API origin 与前端 origin 不同，不能把交互式文档中的匿名 Try it out 作为账号写入验收。

### 10.2 邮件 Worker 与数据生命周期

完成私有配置并确认接收测试邮件已获授权后，在 `backend` 目录的独立终端运行：

```powershell
uv run --locked python -m app.mail_worker
```

该进程独立于 API、Mock、Parser、Runner 和 Import Worker；API 事务只写 token 与加密 outbox，不同步发送邮件。`--once` 最多处理一条可领取邮件，仍可能真实发送，不能用作无副作用健康检查。停止 Worker 后待发记录保留在数据库，运行中的投递租约过期后可被其他 Worker 回收。

Worker 以 `FOR UPDATE SKIP LOCKED` 领取 queued 或租约过期的 sending 记录，投递前复核账号、令牌用途/有效期和收件人。单次租约为 `10 * SMTP_TIMEOUT_SECONDS + 60` 秒，写回需匹配 worker_id 且租约有效。每条最多尝试 3 次；可重试传输/4xx 失败依次等待 30 秒、120 秒，并要求令牌在下一次尝试时仍有效。证书、认证、永久拒绝或载荷问题终止；sent/failed 清除加密载荷，只保留脱敏错误分类。SMTP 接受后进程崩溃可能造成重投，收件人只应使用最新有效的一次性链接，不承诺恰好投递一次。

验证邮件链接为 `/verify-email#token=...`，重置链接为 `/reset-password#token=...`；令牌不放查询字符串。前端只解析一次并立即清除地址栏敏感内容，不自动提交、不加载第三方服务。验证必须同时提交邮件令牌与注册时原密码，防止预注册劫持；验证成功后另行登录。忘记密码和重发仅返回通用受理结果，不表明邮箱是否存在或邮件是否已送达。重发撤销同用途旧令牌及其待发载荷；注册后 24 小时未验证的 pending 账号可在后续冲突注册时受控回收。

改密或重置会递增 auth_version，撤销所有会话及未消费邮件令牌；退出仅撤销当前会话。前端在退出、业务 401 或跨标签身份变化时取消旧请求和轮询、隔离旧响应与幂等键，并重挂私有子树清空研究数据，保留语言偏好。其他账号的资源与不存在的资源统一返回 404，PDF、事件、产物和导入历史均须沿归属链校验；私有 API/PDF 应带 no-store，不能通过静态目录绕过下载鉴权。

### 10.3 验收状态与剩余工作

当前本地 QQ SMTP 发件地址与授权码尚未配置。操作者应在忽略的 `.env` 中私下填写；本文与 `.env.example` 不记录真实值。本次自动验收使用邮件替身，没有发送真实邮件或调用真实模型/arXiv。

2026-11-14 本次实施已验证：私下生成账号密钥后本地 check_config 通过，SMTP configured=False；原生 16 项所有权测试和 8 项综述 PostgreSQL 测试通过，实际账号 API 的注册→验证→登录→PDF 上传→密码找回/重置→旧会话撤销链路通过，前端 build 与隔离 auth browser suite 重跑通过。功能已实现，真实 QQ 配置/投递验收仍待完成。审查发现的重置丢失 arXiv gate 问题已复现并修复：reset_data 清表后重新播种，0004 迁移以 INSERT ON CONFLICT 补种，实际配置库的 seed 已修复；成功重置回归已证明 permit 可领取/释放，16 项原生套件通过。schema.sql 已用生成的 Alembic SQL 补齐 0004，隔离 schema 与 ORM 对照回归已纳入原生所有权 16 项通过结果。实际配置数据库已验证 head=20261114_0004、无结构漂移，业务记录/用户/生成文件均为 0，source_request_gates seed 为 1。

真实 QQ SMTP 验收尚未执行：部署者需私下检查授权码和一致发件地址，再以获授权收件人验证实际收信、中文/英文正文、fragment 链接、原密码验证、重置后的全会话失效、重发/过期/限流及永久失败处理。后端中文邮件模板已恢复为中文正文；中文/英文真实收信仍须在 SMTP 验收中确认。

### 10.4 已有开发库的受控重置

当前导出的 `app.reset_data` 保留数据库/schema/Alembic revision，按当前应用元数据识别已有业务表并清空应用记录，同时只处理 STORAGE_ROOT 下 uploads/import-temp 中识别出的 UUID PDF/临时产物；拒绝符号链接、junction 与异常文件。此操作会移除账号及研究数据，不能当成保留旧论文的所有权迁移。本次实施已按用户授权完成旧数据清理，保留 schema 与 Alembic 版本；该工具也可用于后续显式开发库重置。

先停止 API、邮件及全部业务 Worker，备份并私下核对目标数据库名和绝对存储路径。使用与 Settings 完全一致的目标参数，在 backend 目录预览（将占位值替换为已核对目标，不是连接 URL 或密码）：

```powershell
uv run --locked python -m app.reset_data --database <confirmed_database_name> --storage <confirmed_absolute_storage_path>
```

不带 `--execute` 默认为 dry-run，报告数据库名、存储路径、各表行数和文件数量；不能据此声称已清理。确认报告符合已授权清理范围后，操作者在同一条命令后显式添加 `--execute` 才会删除。工具复核实际数据库名、Settings 目标、存储边界；执行模式还拒绝其他 client backend 连接，以独占表锁和 5 秒 lock_timeout 清理，不删除 schema 或 Alembic 版本记录。清表后在同一事务重新插入 arxiv 共享访问 gate，确保后续来源请求可获取许可；0004 的幂等补种同时覆盖历史缺失的 seed。应用表清理提交后再删生成文件，两者不构成原子事务；失败需核对数据库/文件实际状态，不应盲目重复。重置后再执行 `alembic upgrade head`，核对 current/check 并完成双账号验收。

### 10.5 本次实施验证命令与范围

在 `backend` 目录运行已跟踪的原生所有权套件：

```powershell
uv run --locked python tests/test_ownership.py --postgres
```

该入口要求 PostgreSQL 位于 `127.0.0.1`，创建随机命名的 `ownership_tests_<UUID>` 隔离数据库，使用子进程执行测试，并在 finally 中自动 DROP 该隔离库；连接账号须有创建/删除测试库权限。不要手工将已有业务库作为测试目标，不在日志中输出连接凭据。

2026-11-14 本次实施已验证：

| 验证范围 | 最终结果 |
| --- | --- |
| 原生所有权 tests/test_ownership.py --postgres | 16 项全部通过，包含成功重置后 permit 领取/释放及 schema.sql 与 ORM 类型/默认值对照 |
| 账号原生 harness | 74 项全部通过，无跳过 |
| 原生综述 PostgreSQL 套件 | 8 项全部通过 |
| 默认 discover | 共 124 项：68 项通过，56 项因环境门控跳过；门控套件已按上述原生入口分别执行通过 |
| 账号与前端完整链路 | 实际账号 API 注册→验证→登录→PDF 上传→找回/重置→会话撤销通过；前端 build 与隔离 auth browser suite 重跑通过；配额中文消息及对应英文诊断映射已补齐 |
| 实际配置数据库与生成文件 | head=20261114_0004；无结构漂移；业务记录 0、用户 0、生成文件 0；source_request_gates seed 1 |

账号 API 测试使用隔离数据和邮件 outbox/测试替身，不发送真实 QQ 邮件或调用真实模型/arXiv。安全配置已以私下生成的 auth keys 验证通过；SMTP configured=False，真实 QQ 配置与投递验收待完成。默认 discover 的环境门控跳过与单独执行的原生套件结果分别记录，不把跳过当作通过。

### 10.6 审查发现与处置

- 已修复并验证：成功 reset 会清空 source_request_gates，导致 arXiv 持续限流。reset_data 现已在清表事务中补种 arxiv，0004 迁移也以 ON CONFLICT DO NOTHING 恢复 seed；实际配置库已补种，正向重置回归证明许可可领取/释放，原生 16 项测试通过。
- 已补齐：schema.sql 已附加由 Alembic 生成的 0004 SQL；test_reference_sql_matches_current_metadata 在回滚的隔离 reference_schema 执行参考 DDL，比较 ORM 类型/默认值并检查 gate seed，已纳入原生所有权 16 项通过结果。
- 已修复并验证：retry_import 的用户配额锁与 complete_import 的用户外键引用锁可能形成死锁。原生回归 test_import_completion_does_not_deadlock_with_retry_quota_lock 已复现失败；配额锁改为 FOR NO KEY UPDATE，在序列化同用户配额的同时兼容外键 FOR KEY SHARE。相同并发回归及全部 16 项所有权测试通过。

## 11. Agent 资源预算

新任务由后端冻结 Agent 限额。旧客户端仍可发送合法 budget 以兼容请求格式，但该字段不控制新任务；幂等重放按任务创建时的自动/历史手动预算规则核对。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AGENT_MAX_STEPS` | 100 | Agent 最大步骤数 |
| `AGENT_SEARCH_MAX_PAPERS` | 5 | 统一研究允许额外搜索的论文数，选定与搜索合计至多 20 |
| `AGENT_TIMEOUT_SECONDS` | 1800 | 单次任务总期限 |
| `AGENT_OUTPUT_TOKENS` | 8192 | Agent 输出上限 |
| `AGENT_CONTEXT_TOKENS` | 32000 | Agent 上下文窗口 |
| `AGENT_RESULT_MAX_BYTES` | 16777216 | 接收结果大小限制 |

预算写入 manifest 与 task.run_config，修改服务端配置不重置已提交任务。模型实际上下文能力、阅读/检索策略和生成过程由 Agent 管理；后端不再采样 paper_chunks 或计算本地检索 Token 计划。

## 12. 历史兼容与数据库清理边界

本次只删除后端冗余运行代码，不执行删表、清库或历史记录改写。保留以下结构是为了兼容存量结果及数据库约束：

- `paper_chunks` / `PaperChunk`：新解析流程不再读写，存量记录保留为历史引用的外键目标。
- Task 的历史 runner/workflow/prompt/model 字段及 CHECK 约束：允许读取旧 mock/langgraph 记录，不代表仍支持执行旧流程。
- `review_state`：保留，因为 Agent 当前使用其 agent_outcome 保存结果摘要；旧 checkpoint/检索快照只作为历史数据。
- Citation 的历史 chunk_id 与新 Agent 来源/证据字段：同时保留。Agent 证据无需对应 `paper_chunks` 行。
- 旧响应的 `is_mock`、budget 和 `retrieval` 字段：保留兼容形状，`retrieval` 统一为 null，不再计算旧检索诊断。

本次不要求迁移或重置数据库。今后若要物理删除历史表/字段，应先设计历史引用迁移并通过独立 schema 迁移处理，不能直接在生产库 DROP TABLE。旧研究记录不会自动重跑；需要新结果时重新提交 Agent 任务。

## 2026-11-18 导入元数据复用

当前唯一迁移 head 为 `20261121_0008`：保留导入元数据、Agent 派发及 50 MB 大小限制迁移。Agent-only 清理不新增迁移，也不改写历史迁移。仍使用 `alembic upgrade head` / `alembic check`，无需清库或手工 stamp。部署说明见 [后端与 Agent 对接](../docs/agent-backend-integration.md)。

更新后先执行 `uv run --locked alembic upgrade head`（新增可空 `paper_imports.source_metadata`，不改写历史记录），再重启 Import Worker。API 如未开启热重载也需重启。

搜索页新建导入或重试时，服务端优先使用未过期搜索缓存里完全相同版本的已验证元数据，并保存到导入记录。独立 Worker 可跳过重复的 exact-version 元数据 API 请求，直接按受控 URL 下载 PDF。没有快照的历史或直接接口导入仍走原有元数据查询。缓存过期时可重新搜索后手动重试；不会自动重试失败下载。

下载仍受 50 MB 文件限制、TLS/URL 验证、共享访问额度和超时保护。失败日志增加 `stage=metadata/pdf/commit`、`phase`、`elapsed_ms` 和安全错误码，帮助区分来源元数据超时与 PDF 下载超时，不记录密钥或响应正文。
