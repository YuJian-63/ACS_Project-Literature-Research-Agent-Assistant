# 后端开发

当前已实现 MVP-0 API/Mock Worker、MVP-1A 文本 PDF Parser Worker、MVP-1B 真实摘要/问答 Runner、MVP-2 多论文综述与比较表，以及 MVP-3 arXiv 搜索和指定版本 PDF 导入。真实 Runner 使用可替换的模型接口和证据引用校验；尚未实现 OCR。arXiv 默认关闭，真实来源和模型服务需单独配置，不代表本地已完成外部服务验收。接口规范见 `../docs/api-contract.md`。

## 1. 首次启动

需要 Python 3.11+、uv，以及已启动的 Docker Desktop / Docker Engine 和 Docker Compose v2。以下命令在项目根目录开始执行，复制配置仅用于首次创建；已有 `.env` 时跳过复制并检查原配置。

```powershell
cd backend
uv sync --locked
Copy-Item .env.example .env
docker compose up -d --wait postgres
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

保持 API 终端运行，再打开第二个终端，在 `backend` 目录启动 Worker：

```powershell
uv run --locked python -m app.worker
```

API 和 Worker 必须使用同一个数据库及 STORAGE_ROOT。Mock Worker 仅领取 mock 任务；真实模式还需配置 TASK_RUNNER=langgraph、LLM_BASE_URL、LLM_MODEL_ID、LLM_API_KEY，并启动 `python -m app.runner_worker`。未配置模型时，API 返回 `RUNNER_NOT_CONFIGURED`，不创建任务。API 不依赖 FastAPI BackgroundTasks 执行任务，也不自动建表或迁移。

浏览器访问 `http://127.0.0.1:8000/docs` 使用自动生成的交互式接口文档，`/openapi.json` 为机器可读契约。先检查 `/health` 和 `/ready`，再上传 PDF、提交任务并轮询结果。停止 API 和 Worker 不会删除数据库和论文文件。

Linux/macOS 将复制命令替换为 `cp .env.example .env`。其他命令相同。迁移成功后的 revision 是 `20261112_0002`；数据库包含原七张表、新增三张来源/导入/共享访问许可表，以及 Alembic 自己的版本表。`alembic check` 正常输出 `No new upgrade operations detected.`。

依赖版本由 `uv.lock` 固定，当前使用可访问的清华公共 PyPI 镜像，项目不依赖个人机器的全局镜像设置。本次环境访问官方 PyPI 出现 TLS 失败；需要换源时修改 `pyproject.toml` 的 index 并重新生成锁文件，不手工替换锁文件中的包地址。

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
| MOCK_STEP_DELAY_SECONDS | 默认 0.5，范围 0—10；每个模拟步骤的等待秒数，提交时冻结到任务，不影响已有任务 |
| PARSER_TIMEOUT_SECONDS | 默认 120 秒，范围 1—600；限制每份 PDF 的子进程解析时间，超时失败且不会保存部分片段 |
| TASK_RUNNER | 默认 mock；可设 langgraph 选择真实摘要、问答及多论文综述 Runner |
| LLM_BASE_URL / LLM_MODEL_ID / LLM_API_KEY | 真实 Runner 的 OpenAI-compatible 服务地址、模型 ID 与密钥；密钥只从环境读取 |
| LLM_TIMEOUT_SECONDS / EVIDENCE_CONTEXT_CHARS | 单次模型调用超时与证据上下文字符上限 |
| CORS_ORIGINS | JSON 字符串数组；默认允许 localhost:5173 和 127.0.0.1:5173，不接受逗号分隔的裸字符串 |

应用在宿主机运行，示例 DATABASE_URL 连接 `127.0.0.1:5432`。若已有独立 PostgreSQL 17+，可直接配置其 DATABASE_URL，跳过 Compose。修改用户、密码、端口或数据库名时，必须同步修改 DATABASE_URL；已初始化的数据卷不会因为更改 POSTGRES_* 自动修改已有数据库账号。

配置读取顺序为进程环境变量优先于 `backend/.env`；显式传入 Settings 的字段优先级更高。配置文件路径相对后端目录固定，不依赖启动时的当前目录。Compose 的其他字段会被应用配置忽略。

支持 `postgresql://` 和 `postgresql+psycopg://`，统一使用 psycopg 3；拒绝 SQLite、其他驱动及缺少数据库名的地址。密码包含 `@`、`%`、`#`、`/` 等保留字符时先做 URL 百分号编码，不需要为 Alembic 再将 `%` 写成 `%%`。连接密码应放在 @ 前的 userinfo 中；拒绝 password、sslpassword 查询参数，避免 Engine/URL 默认展示泄露查询参数中的密码。连接地址不经过 INI 插值，Settings 默认展示和配置错误文本会隐藏敏感输入；不要主动输出解密后的配置。

## 3. 代码入口

| 文件 | 职责 |
| --- | --- |
| src/app/config.py | 读取并校验 Settings，连接地址使用 SecretStr |
| src/app/db/base.py | DeclarativeBase、UUID 和时间字段 |
| src/app/db/models.py | Paper、PaperChunk、Task、TaskPaper、TaskEvent、Artifact、Citation |
| src/app/db/session.py | 显式创建 Engine 和 Session 工厂 |
| src/app/main.py | 应用工厂、生命周期、请求 ID、统一错误及本地 CORS |
| src/app/api.py、schemas.py、views.py | HTTP 路由、严格请求/响应模型、资源展示 |
| src/app/storage.py | PDF 校验、受控存储、写入补偿和提交结果核对 |
| src/app/pdf_parser.py | 纯文本提取、物理页码分块、内容 hash 与解析资源边界 |
| src/app/parser_worker.py | 独立解析子进程、租约心跳、超时终止和恢复 |
| src/app/parse_lifecycle.py | uploaded 领取、所有权、原子写 chunks/ready 与租约回收 |
| src/app/evidence.py | Agent 内部只读、有界分页的已就绪论文片段读取 |
| src/app/tasks.py | 请求规范化、SHA-256 幂等哈希、任务及来源原子创建 |
| src/app/lifecycle.py、worker.py | 领取、独立心跳、事件、原子完成、恢复和 Mock Worker 命令入口 |
| alembic/env.py | 在线连接与无需凭据的离线迁移 |
| alembic/versions/20261110_0001_initial_schema.py | 冻结的初始结构及逆向迁移 |
| sql/schema.sql | 设计对照，不与 Alembic 在同一数据库重复执行 |

模块导入不读取配置、不连接数据库、不自动建表。调用方显式创建 Engine；连接使用 READ COMMITTED 和 UTC，启用连接存活检查。短事务使用 Session 的 begin 上下文，调用方在服务退出时释放 Engine：

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

数据库默认值在 INSERT/flush 后产生；模型构造时不能假设 id、status 或 created_at 已填充。更新时显式维护 updated_at；没有自动更新时间触发器。JSONB 内容修改使用整体重新赋值，不依赖对普通 dict 的原地修改触发 ORM 更新。可空 JSONB 字段显式配置 none_as_null=True，Python None 写入 SQL NULL，而不是 JSON null。

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

不加 `--sql` 的 `alembic downgrade base` 会实际删除业务表及其中数据，只适用于可丢弃开发库；新迁移在存在导入或来源记录时拒绝降级，不能通过删除来源绕过保护。停止本地数据库可执行 `docker compose down`，该命令保留命名数据卷。

## 5. 已执行验证与边界

2026-11-10 使用临时脚本完成：

- 12 项配置、密码脱敏、凭据查询参数拒绝、环境优先级、延迟连接、模型编译、迁移版本图、模板与离线迁移检查通过。
- 参考 DDL、迁移 SQL、ORM SQL 的数据库目录对照一致：85 个业务字段，主键/外键/CHECK/唯一约束及索引一致。
- 在 PostgreSQL 18.6 / PGlite 0.5.16 上，迁移和 ORM 生成的 SQL 分别通过原有 68 项约束验证。
- psycopg 经临时本机 socket 执行在线升级、重复升级、ORM 读写、可空 JSONB 显式 None、事务回滚、幂等键冲突、Alembic 无漂移检查、降级与重新升级，18 项检查通过。
- Docker Compose 配置解析通过；本机 Docker 守护进程未运行，未实际启动 PostgreSQL 容器。

PGlite socket 不等价于原生 PostgreSQL 多连接模型。PostgreSQL 17+ 上的安装启动、真实多 Worker 竞争、锁/超时及后续 HTTP 集成仍需在相应环境验收。当前没有引入测试框架；临时校验脚本位于忽略的 runtime 目录，不是发布的后端运行依赖。

2026-11-11 增量验证：14 组 HTTP/数据库集成检查通过，覆盖统一错误与跨域头、PDF 头/文件名/精确 20 MiB 上限、重复上传、字面搜索、来源与预算校验、幂等规范化/重放/冲突、唯一冲突后的新事务重查、无 Worker 保持 queued、事件游标、Mock 产物、原子回滚、失联/超时与旧 Worker 写入拒绝、文件写入失败及不确定提交补偿。此前 12 项数据库基础校验也通过回归。

独立 Uvicorn/Worker 进程及真实 Runner 的 PGlite 集成验证记录在忽略的 runtime 脚本中；PGlite 不等价于原生 PostgreSQL 多连接事务，本机 PostgreSQL 17+ 双 Worker 竞争与锁行为仍需部署环境验收。httpx 是 Runner 的运行时 HTTP 依赖。

## 6. 最小业务闭环

在 API 和 Worker 均启动后，可用 `/docs` 顺序调用论文上传、任务创建、任务详情、events、artifacts。也可在第三个 PowerShell 终端中执行，将示例 PDF 路径替换为实际路径：

```powershell
$pdfPath = 'C:\path\paper.pdf'
$paper = curl.exe -sS -F "file=@$pdfPath" http://127.0.0.1:8000/api/v1/papers | ConvertFrom-Json
$body = @{ task_type = 'summary'; paper_ids = @($paper.id) } | ConvertTo-Json
$key = [guid]::NewGuid().ToString()
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/tasks -ContentType 'application/json' -Headers @{ 'Idempotency-Key' = $key } -Body $body
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/tasks/$($task.id)"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/tasks/$($task.id)/events?after_seq=0"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/tasks/$($task.id)/artifacts"
```

任务进入 succeeded/failed 前每 2 秒查询一次，终态后停止。刷新页面或重启 API 后以 task_id 恢复查询。仅网络重试复用同一个幂等键；主动重跑使用新键。Mock summary/qa 选择一篇论文，review 选择 2—20 篇且必须填写问题；extended 返回 WORKFLOW_NOT_AVAILABLE。模拟流程需要两步，max_steps=1 会以 BUDGET_EXCEEDED 失败；不会伪造 token 或模型调用统计。

## 7. 运行边界与恢复

- 仅用于受信本机单用户环境，无鉴权；API 默认绑定 127.0.0.1。公开部署前另行添加身份验证、访问控制、TLS、代理上传限制及配额。
- 上传实际文件最大 20 MiB，分块统计大小并计算 SHA-256；额外限制 multipart 整体为 20 MiB + 64 KiB，避免解析阶段无限写临时文件。上传只检查 PDF 文件头；未启动独立 Parser Worker 时论文保持 uploaded，page_count/parser_version 为 null。
- Mock Worker 领取事务使用行锁及 SKIP LOCKED，租约 60 秒，独立心跳 20 秒；开始时间后的 timeout_seconds 到期优先标为 TASK_TIMEOUT，否则租约到期标为 WORKER_LOST。不自动重跑失联任务，旧 Worker 不能覆盖失败结果。
- 模拟产物明确标注未分析论文、引用为空、比较表为 null。真实 Runner 仅支持摘要/问答，验证来源片段、页码和原文后原子写入产物与引用。
- 上传在明确未提交时清除本次临时/目标文件；提交结果不确定时保留文件并新建会话核对。暂时无法确认返回 503，日志仅记录 paper_id；请先查询论文列表，不要直接删除 uploads 下文件。当前没有自动孤儿文件清理命令，人工核对需先确认原事务已结束，并保留宽限期及备份。
- 默认上传目录和临时验证产物均被 Git 忽略；自定义 STORAGE_ROOT 应放在仓库外或自行确认 ignore 规则。停止所有服务时不会即时恢复任务，下一次 API/Worker 启动时恢复。

前端论文库、上传交互和任务详情/轮询页已提供，启动与联调说明见 `../frontend/README.md`。以下命令在 API 和 Mock Worker 保持运行时，新开第三个终端：

```powershell
cd backend
uv run --locked python -m app.parser_worker
```

Parser Worker 与 API/Mock Worker 必须使用相同的数据库和 `STORAGE_ROOT`。未启动时上传文件仍可用于既有 Mock 任务，但论文保持 `uploaded`；真实证据读取仅在应用内部 `app.evidence.read_evidence(...)` 开放，不新增公开原文片段 API。Parser Worker 默认可并行启动多个实例并使用论文行锁领取不同论文，但 PGlite 不代表已完成 PostgreSQL 多连接竞争验收。

MVP-1A 使用 pypdf 提取文本，不运行 OCR。默认拒绝超过 500 页、8 MiB 提取文本、10000 个片段、单页 16 MiB 解码内容流的文档；连续片段最大 2000 字符。超限不做部分成功；worker 子进程有 120 秒 wall-clock 超时。内容流限制在 pypdf 解码后检查，**不等同于操作系统 RAM 上限**；服务于不可信公网 PDF 前，应在操作系统/容器层加入内存、CPU、磁盘和并发限制。加密、损坏、空扫描件解析失败后不会保留 chunk，需重新上传创建新论文 ID 重试。

此阶段没有新增数据库迁移；真实 Runner 复用既有 paper_chunks、citations 和 artifact 表。启动 Parser Worker 不会修改已有任务/原文件/hash；Mock Runner 仍不读取 chunks，也不产生研究证据或真实结论。原生 PostgreSQL 17+ 多连接、并行 Worker 和进程资源隔离仍需部署环境验收。

## 8. 真实 Runner（可选）

默认 `TASK_RUNNER=mock`，维持模拟结果。需要运行真实摘要、问答或综述时，在 `backend/.env` 设置 `TASK_RUNNER=langgraph`、`LLM_BASE_URL`、`LLM_MODEL_ID` 和 `LLM_API_KEY`；地址须指向 OpenAI-compatible Chat Completions 服务。`LLM_API_KEY` 只从环境读取，不写入任务或日志。真实 Runner 仅接受已解析完成的 ready 论文：summary/qa 一篇，review 2—20 篇且必须填写问题。

保持 API 与 Parser Worker 运行，在另一个终端启动真实 Runner：

```powershell
cd backend
uv run --locked python -m app.runner_worker
```

Mock 与真实 Runner 分别领取对应队列。当前没有可用远端模型凭据时，可用假模型测试逻辑，但不声称真实供应商联调已完成。

综述先为每篇有片段的论文预留一个最短片段，再按问题相关度轮流追加证据，受总字符数和 32 个片段上限约束。最小覆盖无法满足时以 `BUDGET_EXCEEDED` 失败，不调用模型或写部分产物。所有论文均无片段时，不调用模型，返回明确的证据不足和逐篇证据状态表，Token/模型/工具计数均为 0。部分论文无证据时，其比较内容为 null，不编造结论。

正常综述使用单次模型调用，步骤预算至少 1；输出上限为剩余 Token 预算与 2048 的较小值，多篇/多列结果过长可能因结构不完整而校验失败。表格恰好覆盖所有选定论文；每个非空研究内容单元格必须引用本行论文的有效原文，服务端统一生成 C 编号后与正文、引用、usage 和成功状态原子写入。引用来源一致只证明可追溯，不等于语义正确性已获得人工验收。

## 9. arXiv 搜索与导入（MVP-3）

### 开启步骤

1. 启动 Docker Desktop，等引擎就绪。先按第 1 节启动 PostgreSQL；已有数据库先备份，再运行 `uv run --locked alembic upgrade head` 和 `uv run --locked alembic check`，确认 revision 为 `20261112_0002`。不要执行 schema.sql 或删除数据卷。
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
5. 需要查看任务产物时继续运行 Mock Worker（无需模型）或单独配置真实 Runner；Mock 结果不代表论文结论。关闭联网只需设 `ARXIV_ENABLED=false`、重启 API 并停止 Import Worker；历史和手动上传不受影响。

### 实现与限制

- 搜索只访问固定官方 HTTPS API；PDF 只允许同版本官方路径和最多 2 次受控重定向，不接收客户端 URL、代理或下载路径。查询最多 200 字符/20 词、每页最多 20 篇、offset 至多 1000。
- 搜索缓存仅保存上游成功元数据，600 秒/100 页；每次查询重新投影本地导入和解析状态。来源关闭或缺少邮箱返回 `503 ARXIV_NOT_CONFIGURED`，读取历史不要求联网配置。
- API 和所有 Import Worker 共用数据库许可：一次一个来源请求，完成后至少 3 秒，429/503 应用 Retry-After。Worker 首次等待许可受 180 秒总尝试限制；取得许可后元数据预算 20 秒，PDF 含重定向/后续许可等待共用 90 秒，读/连超时各 5 秒，PDF 最大 20 MiB。
- 网络在最小环境的独立子进程运行；父进程可终止超时/取消请求，子进程也有独立总时限 watchdog，避免父进程异常后连接跨越 120 秒许可租约。此为本机 MVP 防护，不是 OS 级内存/CPU/权限沙箱。
- 导入 lease 30 秒/心跳 10 秒；同一版本始终复用一条导入记录。普通 POST 不重试失败，显式重试必须携带 `expected_attempt`；响应丢失后的重放不增加额外 attempt。
- 下载完成才原子发布 Paper(uploaded)、PaperSource 和导入成功，随后由现有解析器独立处理。导入不会生成研究产物/引用，也不按文件 hash 合并手动上传。
- 回滚清理、超时恢复和提交结果核对都通过 Import 行锁/attempt fencing 保护；不确定事务结果时保留最终文件，等待恢复，不删除可能已被成功论文引用的 PDF。不得手工重用 UUID 路径。

### 验收边界

2026-11-12 已在隔离 PGlite 检查旧结构升级、降级保护、三表约束、ORM/迁移/DDL 等价、共享访问许可、缓存、导入 API、Worker/解析器、重试重放和事务/文件补偿。真实子进程测试覆盖大小/安全 URL/超时/停止/父监督缺失；浏览器使用受控夹具验证搜索状态及完整独立进程闭环。

2026-11-13 用户在独立 PostgreSQL 17.6 验收库完成 head 迁移、无结构漂移检查及八组原生多进程/行锁/恢复/共享许可专项验收。随后真实搜索一次、导入 `2512.19700v1`，重复提交复用同一记录且 attempt=1；独立 Import Worker 完成下载，Parser Worker 将本地 PDF 解析为 ready（9 页）。用户同时确认前端历史恢复、来源与本地 PDF 访问、论文预选、Mock 任务成功及结果刷新恢复。上述证据来自用户提供的输出和人工确认，未由代理独立重跑；详细标识与记录见 `../docs/superpowers/plans/2026-11-12-mvp-3-arxiv-search-import.md`。

原生验收覆盖八组专项场景，不代表此前全部 PGlite 故障注入均已在原生环境重跑。真实来源验收仅覆盖一次搜索和一个版本下载，不代表真实上游限流、重定向或故障已被人工触发。Mock 结果不代表论文结论；MVP-2.1 的真实模型验证仍独立待办。
