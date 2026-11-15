# 后端开发

当前已实现 MVP-0 API/Mock Worker、MVP-1A 文本 PDF Parser Worker、MVP-1B 真实摘要/问答 Runner、MVP-2 多论文综述与比较表，以及 MVP-3 arXiv 搜索和指定版本 PDF 导入。真实 Runner 使用可替换的模型接口和证据引用校验；尚未实现 OCR。arXiv 默认关闭，真实来源和模型服务需单独配置，不代表本地已完成外部服务验收。接口规范见 `../docs/api-contract.md`。2026-11-14 账号、配置校验、Cookie/CSRF、私有资源归属和所有权迁移已实现；真实 QQ SMTP 配置与投递验收待完成。首次启动前先阅读第 10 节。

## 1. 首次启动

需要 Python 3.11+、uv，以及已启动的 Docker Desktop / Docker Engine 和 Docker Compose v2。以下升级命令只适用于新建空业务库；已有数据时 `20261114_0004` 会拒绝升级，必须先停服务、核对备份并按第 10 节处理，不能直接清表或绕过保护。以下命令在项目根目录开始执行，复制配置仅用于首次创建；已有 `.env` 时跳过复制并检查原配置。

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

浏览器访问 `http://127.0.0.1:8000/docs` 使用自动生成的交互式接口文档，`/openapi.json` 为机器可读契约。先检查 `/health` 和 `/ready`，再通过前端注册、验证邮箱并登录后上传 PDF、提交任务和轮询结果。健康检查不证明账号/SMTP 配置或投递已通过。停止 API 和 Worker 不会删除数据库和论文文件。

Linux/macOS 将复制命令替换为 `cp .env.example .env`。其他命令相同。当前迁移目标 revision 是 `20261114_0004`；数据库包含原七张业务表、三张来源/导入/共享访问许可表和五张账号表（共 15 张，不含 Alembic 版本表）。`alembic check` 正常输出 `No new upgrade operations detected.`。

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
| LLM_THINKING_MODE | provider_default（默认）不发送思考参数；disabled/enabled 显式发送 thinking.type，仅用于支持该扩展的模型服务；提交任务时冻结 |
| LLM_TIMEOUT_SECONDS / EVIDENCE_CONTEXT_CHARS | 单次模型调用超时与证据上下文字符上限 |
| CORS_ORIGINS | JSON 字符串数组；默认允许 localhost:5173 和 127.0.0.1:5173，不接受逗号分隔的裸字符串 |

应用在宿主机运行，示例 DATABASE_URL 连接 `127.0.0.1:5432`。若已有独立 PostgreSQL 17+，可直接配置其 DATABASE_URL，跳过 Compose。修改用户、密码、端口或数据库名时，必须同步修改 DATABASE_URL；已初始化的数据卷不会因为更改 POSTGRES_* 自动修改已有数据库账号。

配置读取顺序为进程环境变量优先于 `backend/.env`；显式传入 Settings 的字段优先级更高。配置文件路径相对后端目录固定，不依赖启动时的当前目录。Compose 的其他字段会被应用配置忽略。

支持 `postgresql://` 和 `postgresql+psycopg://`，统一使用 psycopg 3；拒绝 SQLite、其他驱动及缺少数据库名的地址。密码包含 `@`、`%`、`#`、`/` 等保留字符时先做 URL 百分号编码，不需要为 Alembic 再将 `%` 写成 `%%`。连接密码应放在 @ 前的 userinfo 中；拒绝 password、sslpassword 查询参数，避免 Engine/URL 默认展示泄露查询参数中的密码。连接地址不经过 INI 插值，Settings 默认展示和配置错误文本会隐藏敏感输入；不要主动输出解密后的配置。

## 3. 代码入口

后端按职责分包。`app/` 根目录仅保留应用工厂、共享配置/错误，以及兼容既有命令的四个 Worker 启动入口；业务实现放入对应子包。

```text
src/app/
├── main.py                   # 应用工厂、中间件与资源生命周期
├── config.py / errors.py     # 共享配置与统一业务错误
├── api/                     # HTTP 层
│   ├── router.py            # health / papers / tasks 路由组合
│   ├── health.py            # 存活与数据库迁移就绪检查
│   ├── papers.py            # 上传、列表、详情与本地 PDF
│   ├── tasks.py             # 任务提交、状态、事件与产物
│   ├── imports.py           # 来源搜索、导入历史和重试
│   ├── pagination.py        # 通用分页参数
│   └── schemas.py / views.py
├── auth/                    # 账号 API、会话/CSRF、限流与加密邮件 outbox
├── db/                      # SQLAlchemy 业务/账号模型与数据库连接
├── papers/                  # storage、pdf_parser、解析 lifecycle、evidence
├── research/                # model_client、graph、retrieval、validation
├── sources/                 # arxiv、arxiv_transport、access、imports
├── tasks/                   # service：提交/查询；lifecycle：领取/完成/恢复
├── workers/                 # mock、parser、research、imports 进程实现
├── mail_worker.py           # 独立 QQ SMTP 投递进程
└── worker.py / parser_worker.py / runner_worker.py / import_worker.py
                             # 仅转发 main，保留原有启动命令
```

| 文件 | 职责 |
| --- | --- |
| src/app/config.py | 读取并校验 Settings，连接地址使用 SecretStr |
| src/app/db/base.py | DeclarativeBase、UUID 和时间字段 |
| src/app/db/models.py | Paper、PaperChunk、Task、TaskPaper、TaskEvent、Artifact、Citation |
| src/app/db/accounts.py | User、AuthSession、AuthEmailToken、AuthMailOutbox、AuthRateBucket 五张账号表 |
| src/app/auth/、src/app/mail_worker.py | 注册/验证/登录/找回、Cookie/CSRF、数据库限流与独立 SMTP Worker |
| src/app/db/session.py | 显式创建 Engine 和 Session 工厂 |
| src/app/main.py | 应用工厂、生命周期、请求 ID、统一错误及本地 CORS |
| src/app/api/ | 按 health/papers/tasks/imports 拆分路由；schemas 和 views 定义公开模型与资源展示 |
| src/app/papers/storage.py | PDF 校验、受控存储、写入补偿和提交结果核对 |
| src/app/papers/pdf_parser.py | 纯文本提取、物理页码分块、内容 hash 与解析资源边界 |
| src/app/papers/lifecycle.py | uploaded 领取、所有权、原子写 chunks/ready 与租约回收 |
| src/app/papers/evidence.py | Agent 内部只读、有界分页的已就绪论文片段读取 |
| src/app/research/ | 模型客户端、单次生成工作流、证据检索、引用/比较表校验 |
| src/app/sources/ | arXiv 客户端及受监督子进程、共享许可/搜索缓存、持久化导入 |
| src/app/tasks/service.py | 请求规范化、SHA-256 幂等哈希、任务及来源原子创建 |
| src/app/tasks/lifecycle.py | 领取、心跳、事件、原子完成与失联恢复 |
| src/app/workers/ | 四类 Worker 的进程循环、心跳、超时和资源释放 |
| src/app/*_worker.py、worker.py | 原有命令启动入口；内部代码直接导入 workers 中的实现 |
| alembic/env.py | 在线连接与无需凭据的离线迁移 |
| alembic/versions/20261110_0001_initial_schema.py | 冻结的初始结构及逆向迁移 |
| alembic/versions/20261114_0004_user_accounts.py | 五张账号表、非空资源归属、用户内幂等/来源唯一性；拒绝非空旧业务库及降级 |
| sql/schema.sql | 空 schema 的设计对照，已用生成的 Alembic SQL 补齐 0004；不与迁移在同一数据库重复执行；原生对照回归见 tests/test_ownership.py |

API 组织 HTTP 参数和响应；tasks/papers/sources 管理对应数据与生命周期；research 处理模型输入和校验；workers 编排独立进程。此次整理保留既有函数和依赖关系，不新增仓储抽象或改变事务边界。历史实施记录中的旧文件路径保留为当时记录；当前代码路径以本节为准。

API 仍使用 `uvicorn app.main:create_app --factory`。四个 `python -m app.worker` / `app.parser_worker` / `app.runner_worker` / `app.import_worker` 命令保持不变。若自编脚本直接导入内部类或函数，请改为 `app.workers.research.RunnerWorker`、`app.tasks.service.submit_task` 等新路径；共享 `app.config.Settings`、数据库导入路径及 `.env`/存储根目录不变。重启现有进程时仍使用原终端，以保留会话环境变量；上述模块整理本身不需要迁移；账号功能另需 `20261114_0004`，见第 10 节。

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

`20261114_0004` 明确拒绝降级，不能恢复匿名共享访问；需要回退时只能按已核验的升级前备份恢复。旧 revision 的 downgrade 可删除业务表及数据，来源迁移也有拒绝非空降级保护；这些历史能力不能作为绕过 0004 保护的方式。停止本地数据库可执行 `docker compose down`，该命令保留命名数据卷。

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

账号路由、归属与凭据 CORS 已集成；在 API、邮件 Worker 及业务 Worker 启动并补齐邮件配置后，通过前端完成以下闭环：

1. 注册用户名、邮箱和密码，在获授权收件箱打开验证链接，并输入注册时原密码完成验证。
2. 使用用户名和密码登录，确认账户菜单显示真实用户名。
3. 上传 PDF，按需等待 Parser 就绪；选择论文后提交任务。前端自行保存 HttpOnly Cookie，并为上传/任务 POST 添加 CSRF 与幂等键。
4. 查询任务详情、events、artifacts，并刷新恢复；退出后确认私有界面与请求停止，另一个账号无法读取原论文、PDF 或任务。

手动 HTTP 客户端同样需先在可信 Origin 下 JSON 登录，保留 Cookie 和返回的 csrf_token；读取携带 Cookie，业务写入另带匹配 Origin 与 X-CSRF-Token，任务 POST 再带 Idempotency-Key。不要把密码、Cookie 或令牌放入命令历史。`/docs` 的 API origin 不自动满足可信前端 Origin，原有匿名 curl 上传/提交方式不再适用。

任务进入 succeeded/failed 前每 2 秒查询一次，终态后停止。刷新页面或重启 API 后以 task_id 恢复查询。仅网络重试复用同一个幂等键；主动重跑使用新键。Mock summary/qa 选择一篇论文，review 选择 2—20 篇且必须填写问题；extended 返回 WORKFLOW_NOT_AVAILABLE。模拟流程需要两步，max_steps=1 会以 BUDGET_EXCEEDED 失败；不会伪造 token 或模型调用统计。

## 7. 运行边界与恢复

- API 默认绑定 127.0.0.1。账号接入后业务接口必须以验证后的用户身份限定资源归属；公开部署仍需完成集成验收并配置 HTTPS、Secure Cookie、可信代理/Origin、上传限制和资源配额，见第 10 节。
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

Parser Worker 与 API/Mock Worker 必须使用相同的数据库和 `STORAGE_ROOT`。未启动时上传文件仍可用于既有 Mock 任务，但论文保持 `uploaded`；真实证据读取仅在应用内部 `app.papers.evidence.read_evidence(...)` 开放，不新增公开原文片段 API。Parser Worker 默认可并行启动多个实例并使用论文行锁领取不同论文，但 PGlite 不代表已完成 PostgreSQL 多连接竞争验收。

MVP-1A 使用 pypdf 提取文本，不运行 OCR。默认拒绝超过 500 页、8 MiB 提取文本、10000 个片段、单页 16 MiB 解码内容流的文档；连续片段最大 2000 字符。超限不做部分成功；worker 子进程有 120 秒 wall-clock 超时。内容流限制在 pypdf 解码后检查，**不等同于操作系统 RAM 上限**；服务于不可信公网 PDF 前，应在操作系统/容器层加入内存、CPU、磁盘和并发限制。加密、损坏、空扫描件解析失败后不会保留 chunk，需重新上传创建新论文 ID 重试。

此阶段没有新增数据库迁移；真实 Runner 复用既有 paper_chunks、citations 和 artifact 表。启动 Parser Worker 不会修改已有任务/原文件/hash；Mock Runner 仍不读取 chunks，也不产生研究证据或真实结论。原生 PostgreSQL 17+ 多连接、并行 Worker 和进程资源隔离仍需部署环境验收。

## 8. 真实 Runner（可选）

默认 `TASK_RUNNER=mock`，维持模拟结果。需要运行真实摘要、问答或综述时，在 `backend/.env` 设置 `TASK_RUNNER=langgraph`、`LLM_BASE_URL`、`LLM_MODEL_ID` 和 `LLM_API_KEY`；地址须指向 OpenAI-compatible Chat Completions 服务。`LLM_API_KEY` 只从环境读取，不写入任务或日志。真实 Runner 仅接受已解析完成的 ready 论文：summary/qa 一篇，review 2—20 篇且必须填写问题。

DeepSeek 本轮验收使用官方服务和本地密钥，并设置 `LLM_THINKING_MODE=disabled`，显式关闭思考后先验证单篇摘要和引用；单篇任务保持 2048 Token 生成上限，新综述的独立输出预算调整见下文。其他服务保持默认 `provider_default`，请求中不附加 `thinking`。此模式随新任务冻结到 run_config，旧任务缺少该字段时仍使用 provider_default；Worker 后续修改配置不改变已提交任务的模式。设置 disabled 不保证输出必然完整，仍需真实任务验收。

进程环境变量优先于 `.env`。从其他工具或终端继承了模型地址/密钥时，应在用于启动 API 和真实 Runner 的各自终端清除对应覆盖，再读取本地配置。只检查地址、模型、思考模式和密钥是否存在，不打印密钥；配置齐全不代表服务可用或密钥有效。

真实任务若以 `INVALID_AGENT_RESULT` 失败，接口 error.details 中的 validation_reason 会区分 invalid_json、schema_mismatch、quote_mismatch、unknown_evidence、引用标记/序号/未使用/重复引用等原因；model_finish_reason 仅保存模型结束原因的白名单值（如 stop、length），未知值记录 unknown。Worker 日志仅记录任务 ID 和这两个分类，不记录提示、模型正文、论文原文或密钥。校验仍严格拒绝非逐字引文和越界来源；没有自动重试，失败不发布产物。旧失败记录没有这些诊断，不能据此推断原始失败原因，也不会被修改。

新建真实 summary/qa 任务使用 `evidence-v4`：后端将选中的存储文本分为最长 1000 字符的连续证据片段，提供 E1 等任务内 ID；模型返回 paragraphs，每段包含 content_markdown 与支持该段的 evidence_ids。后端按 ID 取原样引文、片段身份和物理页码，并统一生成引用编号；模型不再自行抄写引文或 UUID。没有模糊匹配或排版归一化，最终仍执行逐字来源与大小校验。未知 ID、同段重复 ID、模型自写编号或额外 quote/来源字段会失败。paragraphs/evidence_ids 仅是内部模型协议，对外产物仍为 content_markdown 与 citations，无需更改前端或数据库。

版本随任务保存并由 Runner 按原版本执行；已有 `evidence-v1`/`evidence-v2`/`evidence-v3` 任务及 `evidence-review-v1` 综述规则保持原行为。升级后须重启 API 和真实 Runner，再新建任务验收；旧任务和幂等重放不会自动切换版本。2026-11-13 真实问答在 v2 下出现 `unused_citation`，v3 则出现 `quote_mismatch`，两次结束原因均为 `stop`。v4 将原文提取也交由后端完成，不增加模型调用或自动重试；本次真实问答执行及人工验收记录见下，不能以本地测试代替真实验收。设计见 `../docs/superpowers/specs/2026-11-13-evidence-selection.md`。

新建真实 review 使用 `evidence-review-v2`，工作流版本仍为 `langgraph-review-v1`。复用同一原样证据摘录机制，输入证据额外标明所属 paper_id，E 编号在整个任务内唯一。模型返回 paragraphs 和 comparison_table：正文段落与表格单元格均只选择 evidence_ids，单元格仍有 value。后端先遍历段落，再按选定论文及声明列顺序遍历表格，为同一证据统一分配 C 编号；允许证据只用于表格。非 null 的研究单元格必须选择本行论文的证据，未报告信息用 null 和空 evidence_ids。未知/重复 ID、跨论文单元格引用、伪造引文/页码/引用编号字段及正文、单元格、列标题中的模型自写引用标记均会失败，不做修复或重试。最终仍复用既有严格综述校验，外部正文、引用和比较表结构不变，无需数据库迁移。旧版或缺少提示版本的 review 任务继续按 v1 执行，不自动升级。设计及验证记录见 `../docs/superpowers/specs/2026-11-13-review-evidence-selection.md`。

保持 API 与 Parser Worker 运行，在另一个终端启动真实 Runner：

```powershell
cd backend
uv run --locked python -m app.runner_worker
```

Mock 与真实 Runner 分别领取对应队列。当前没有可用远端模型凭据时，可用假模型测试逻辑，但不声称真实供应商联调已完成。

2026-11-13 真实单篇摘要验收：DeepSeek `deepseek-flash`、thinking=disabled，任务 `e12f73c7-6f45-45da-a784-75807081101d` 已成功，非 Mock，模型调用 1 次，记录输入/输出 Token 为 7650/759。API 读取确认持久化结果及 5 条所选论文引用；用户人工确认正文显示、引文/物理页码、结论支持和刷新恢复均正常。此前一次 INVALID_AGENT_RESULT 原因未能追溯，后续成功不等于生成问题已修复。多论文综述及正式测试/CI 仍待后续验收；详见 `../docs/superpowers/plans/2026-11-13-model-thinking-mode.md`。

2026-11-13 真实单篇问答验收通过：任务 `27da56a0-a3aa-4f0b-b1d7-9aa04cde0231` 使用 `evidence-v4`，已成功，非 Mock，模型调用 1 次，输入/输出 Token 为 6733/528。独立读取确认 7 条引用均在正文使用，逐字匹配已存原文，页码与来源片段一致，且来自 v4 证据表。用户人工确认回答覆盖数据、分析方法和局限，未报告信息明确说明，7 条引文及物理页码、结论支持、PDF 导航和刷新恢复均正常。该结论限于本次任务，不代表一般生成可靠性或真实多论文综述已验收。

综述先为每篇有片段的论文预留一个最短片段，再按问题相关度轮流追加证据，受总字符数和 32 个片段上限约束。最小覆盖无法满足时以 `BUDGET_EXCEEDED` 失败，不调用模型或写部分产物。所有论文均无片段时，不调用模型，返回明确的证据不足和逐篇证据状态表，Token/模型/工具计数均为 0。部分论文无证据时，其比较内容为 null，不编造结论。

历史 `langgraph-review-v1` 综述使用单次模型调用，步骤预算至少 1。该历史工作流后期提交的综述由服务端冻结 `run_config.max_output_tokens=4096`；实际请求上限为该值与「任务总 Token 预算减去预估输入」的较小值。预估输入已耗尽总预算时不调用模型，返回 `BUDGET_EXCEEDED`；调用后仍以供应商报告的实际输入/输出用量检查总预算。旧任务缺少该字段时保持 2048，包括已存在的 review-v2；摘要、问答及 Mock 不变。字段不接受客户端指定；持久化值必须为精确整数，review 仅支持 2048/4096，单篇仅支持 2048，异常值执行前失败。增加上限可能增加费用，不保证 JSON 一定完整；截断仍严格失败，不自动续写、修补 JSON 或重试。表格恰好覆盖所有选定论文；每个非空研究内容单元格必须引用本行论文的有效原文，服务端统一生成 C 编号后与正文、引用、usage 和成功状态原子写入。引用来源一致只证明可追溯，不等于语义正确性已获得人工验收。

历史任务 `6111bd43-31fb-449b-ab42-f0605a35ae27` 已实际到达官方模型，但返回 `INVALID_AGENT_RESULT`，details 为 `invalid_json` / `length`。只读核对确认其总预算 16000、预估输入 10780，Worker 当时仍把输出限制为 2048。随后实施新建真实综述冻结 4096 输出上限的调整，并指导用户在保留正确密钥的原终端分别重启 API 与真实 Runner；重启不会改写旧任务或幂等重放的配置。新建验收沿用两篇 ready 论文、总预算 16000、步骤 10、执行超时 180 秒。

2026-11-13 用户反馈新任务 `3cd9c072-c9f5-4b03-9d91-af2abd358570` 执行成功，并逐项确认真实运行信息、综述正文与比较表、两篇论文引用及 PDF 物理页码、刷新恢复全部正常。本次双论文真实综述端到端人工验收通过；证据为用户反馈，代理未独立重跑或只读核对该任务的冻结配置、实际 Token 用量及完整产物，不声称实际输出超过 2048 或证明普遍可靠性。该结果不改变严格引用校验，不解决真实 arXiv 后续超时。详细记录见 `../docs/superpowers/plans/2026-11-13-real-review-acceptance.md`；设计与离线验证见 `../docs/superpowers/specs/2026-11-13-review-output-budget.md`。

### 8.1 自动预算与分阶段综述（2026-11-14）

新建真实 review 使用 `langgraph-review-v2 / evidence-review-v3`，适用于 2—20 篇 ready 论文。前端移除预算输入；后端忽略客户端 review 预算，按论文数量、证据长度、问题及提示词开销冻结 `run_config.review_policy`。摘要、问答与 Mock 的新任务自动预算见第 11 节，历史任务保留原冻结配置。

每篇论文最多采样四个分布于全文的片段，默认每篇共 4000 字符；证据用于研究目标、方法、评估、局限四列。随后分别生成共同点、差异、局限三个短章节，比较表与引用由服务端组装。信息不足时返回 null 或证据不足说明，不推断未采样的实验结果。采样不等于完整阅读全文。

服务器自动尝试更紧凑的内容和证据配置，检查单次上下文、累计 Token、调用数和总时限。默认每次输出最多 4096 Token；任务硬上限仍为 100 次调用、100000 累计 Token、1800 秒。输入 Token 按每个 UTF-8 字节最多一个 Token 加消息开销预留，并非供应商精确分词器，模型上下文和输出限制须由部署者正确配置。即使论文数量在 2—20 篇内，完整证据或较长问题也可能超过累计上限；最低证据额度仍不足时不继续压缩成失去意义的片段。无法容纳时创建返回 `422 REVIEW_CAPACITY_EXCEEDED`，不请求模型。

每个分析/章节最多尝试两次；全任务额外重试最多两次（超过 12 篇时一次），失败只重试当前单元并要求更短输出。JSON、证据 ID、跨论文引用、字符长度和最终逐字引文仍严格校验。重试依然可能失败；所有阶段成功且最终校验通过后才原子发布结果。

`tasks.review_state` 保存证据快照、验证后的阶段结果和调用预留，不保存原始模型输出或密钥。每次请求前先持久化预计用量；无 usage 或结果不确定时保留估算，API 的 `stats.usage_estimated` 标识此情况。失败/无效响应也累计费用估算。Worker 租约到期后在原截止时间内从已保存阶段恢复；旧 Worker 无权补写，不确定请求可能再执行一次，但保留原预留并受全局上限约束。

部署前停止 API 和真实 Runner，保留正确的 `.env` 配置，在 backend 执行：

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

确认 `20261114_0003 (head)` 后分别重启 `uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000` 和 `uv run --locked python -m app.runner_worker`。Parser/Import Worker 如在运行也应重启以加载统一版本。升级保留历史任务。降级0003会删除阶段快照；若存在已恢复且带 started_at 的 queued 任务，旧生命周期约束会阻止降级，须先正常处理任务，不能直接清除记录绕过。

可选部署参数见 `.env.example`：`REVIEW_CONTEXT_TOKENS`、`REVIEW_OUTPUT_TOKENS`、`REVIEW_TASK_TOKENS`、`REVIEW_TIMEOUT_SECONDS`、`REVIEW_CALL_TIMEOUT_SECONDS`、`REVIEW_EVIDENCE_CHARS`。不需要用户为每个任务设置这些值。

开发验证：`PYTHONPATH=backend/src` 下使用 backend 虚拟环境运行 `python -m unittest discover -s backend/tests -q`；原生数据库测试仅在显式提供 `STAGED_REVIEW_TEST_URL` 且目标为本机 55432 或 55433 / review_tests 时启用，不能指向业务库。真实六篇论文验证需创建新任务，观察逐篇/分章进度、完整六行比较表、引用及刷新恢复。

2026-11-14 用户完成上述迁移并确认服务检查正常，新建六篇论文综述任务 `eb3b4c9e-39db-4e19-bd88-5e64faeb9941` 成功。用户人工确认正文完整、六行比较表、正文/表格引用抽查及刷新后的结果和自动分配显示全部正常。本次真实六篇验收通过；代理未独立读取该任务配置、实际用量或重试次数，完整记录见 `../docs/superpowers/plans/2026-11-14-staged-review.md`。

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
5. 需要查看任务产物时继续运行 Mock Worker（无需模型）或单独配置真实 Runner；Mock 结果不代表论文结论。关闭联网只需设 `ARXIV_ENABLED=false`、重启 API 并停止 Import Worker；历史和手动上传不受影响。

### 实现与限制

- 搜索只访问固定官方 HTTPS API；PDF 只允许同版本官方路径和最多 2 次受控重定向，不接收客户端 URL、代理或下载路径。查询最多 200 字符/20 词、每页最多 20 篇、offset 至多 1000。
- 搜索缓存仅保存上游成功元数据，600 秒/100 页；每次查询重新投影本地导入和解析状态。来源关闭或缺少邮箱返回 `503 ARXIV_NOT_CONFIGURED`，读取历史不要求联网配置。
- 搜索来源失败时，API 输出一条安全诊断日志：`request_id`、`phase`、`elapsed_ms`、`code`。阶段仅允许 `connect`、`write`、`pool`、`response_headers`、`response_body`、`deadline`、`source_gate`、`provider_status`、`response_validation`、`unknown`；普通连接失败不进一步推断 TCP/TLS 原因。日志不包含关键词、联系邮箱、原始异常、响应正文或密钥，可用浏览器错误中的请求编号关联。阶段不进入公开错误 envelope。子进程 watchdog 以 124 退出时，父进程明确归类为 `ARXIV_TIMEOUT` / `deadline`。
- API 和所有 Import Worker 共用数据库许可：一次一个来源请求，完成后至少 3 秒，429/503 应用 Retry-After。Worker 首次等待许可受 180 秒总尝试限制；取得许可后元数据预算 20 秒，其中搜索和指定版本元数据的读取等待最多 15 秒，连接/写入/连接池等待最多 5 秒；各阶段均不超过剩余预算，父监督及子进程 watchdog 仍限制整体时长，不自动重试。PDF 含重定向/后续许可等待共用 90 秒，各网络阶段仍最多 5 秒，PDF 最大 20 MiB。
- 网络在最小环境的独立子进程运行；父进程可终止超时/取消请求，子进程也有独立总时限 watchdog，避免父进程异常后连接跨越 120 秒许可租约。此为本机 MVP 防护，不是 OS 级内存/CPU/权限沙箱。
- 导入 lease 30 秒/心跳 10 秒；同一版本始终复用一条导入记录。普通 POST 不重试失败，显式重试必须携带 `expected_attempt`；响应丢失后的重放不增加额外 attempt。
- 下载完成才原子发布 Paper(uploaded)、PaperSource 和导入成功，随后由现有解析器独立处理。导入不会生成研究产物/引用，也不按文件 hash 合并手动上传。
- 回滚清理、超时恢复和提交结果核对都通过 Import 行锁/attempt fencing 保护；不确定事务结果时保留最终文件，等待恢复，不删除可能已被成功论文引用的 PDF。不得手工重用 UUID 路径。

### 验收边界

2026-11-12 已在隔离 PGlite 检查旧结构升级、降级保护、三表约束、ORM/迁移/DDL 等价、共享访问许可、缓存、导入 API、Worker/解析器、重试重放和事务/文件补偿。真实子进程测试覆盖大小/安全 URL/超时/停止/父监督缺失；浏览器使用受控夹具验证搜索状态及完整独立进程闭环。

2026-11-13 用户在独立 PostgreSQL 17.6 验收库完成 head 迁移、无结构漂移检查及八组原生多进程/行锁/恢复/共享许可专项验收。随后真实搜索一次、导入 `2512.19700v1`，重复提交复用同一记录且 attempt=1；独立 Import Worker 完成下载，Parser Worker 将本地 PDF 解析为 ready（9 页）。用户同时确认前端历史恢复、来源与本地 PDF 访问、论文预选、Mock 任务成功及结果刷新恢复。上述证据来自用户提供的输出和人工确认，未由代理独立重跑；详细标识与记录见 `../docs/superpowers/plans/2026-11-12-mvp-3-arxiv-search-import.md`。

原生验收覆盖八组专项场景，不代表此前全部 PGlite 故障注入均已在原生环境重跑。真实来源验收仅覆盖一次搜索和一个版本下载，不代表真实上游限流、重定向或故障已被人工触发，也不代表后续超时已恢复。Mock 结果不代表论文结论；后续真实单篇摘要、问答及双论文综述的独立验收记录见第 8 节，正式测试/CI 仍待办。

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

## 11. 摘要、问答自动预算（2026-11-14）

新建 summary/qa/review 与 Mock 均由后端自动分配执行资源；前端省略 budget，旧客户端的合法 budget 仅作兼容输入，不控制新任务。摘要/问答在创建时冻结选定证据及 single-auto-v1 计划，按完整提示、问题长度及证据规模计算输入预留、动态输出和执行期限。改变服务器配置不影响已提交任务，历史手动预算任务按原请求哈希重放。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| RESEARCH_CONTEXT_TOKENS | 32768 | 单篇任务输入预留与输出上限之和 |
| RESEARCH_OUTPUT_TOKENS | 8192 | 单篇模型输出硬上限，动态值可更小 |
| RESEARCH_TASK_TOKENS | 100000 | 单篇任务累计 Token 硬上限，含余量 |
| RESEARCH_CALL_TIMEOUT_SECONDS | 180 | 单次调用最大秒数，动态值可更短，总任务另加 30 秒 |

这些变量有默认值，已有 .env 无需补填；部署者应按实际模型上下文/输出能力调整。新单篇任务不使用 LLM_TIMEOUT_SECONDS 作为调用上限，旧任务继续使用冻结值。证据过大时缩减采样，仍无法容纳返回 422 RESEARCH_CAPACITY_EXCEEDED；没有匹配证据时不调用模型。自动预算不等于完整阅读全文，也不保证生成不会截断；证据校验及失败处理保持严格，不自动续写或重试单篇调用。综述继续使用 REVIEW_* 配置。

本次调整无需数据库迁移，重启 API 与真实 Runner 后创建新任务即可。隔离 PostgreSQL 回归入口为 uv run --locked python -B tests/test_ownership.py --postgres；策略测试为 uv run --locked python -B -m unittest discover -s tests -p test_task_policy.py -v。

## 12. 跨语言检索与证据覆盖（2026-11-15）

本节更新第 4、9、11 节对新任务的检索/预算描述。新的真实摘要、问答和综述均使用 langgraph-search-v1；原 langgraph-v1、langgraph-review-v2 的已有任务继续走原路径。

- 提交时冻结所选论文的完整解析文本、标题、文件哈希、解析版本及快照摘要；默认上限 8 MiB。只允许当前用户所选论文，不跨用户或联网补证据。
- Worker 内为中文问题生成有限的英文检索表达，原问题始终保留。扩展失败会记录降级事件，使用原问题、内置术语和结构补充检索。
- document_search.py 提供去停用词的中英词面排序、章节覆盖、相邻片段与精确原文窗口。不是向量或语义检索；复杂同义表达仍可能漏召回。
- search_policy.py 为扩展、生成、一次补检索及有限失败恢复预留上下文、Token 和时限。规模大时压缩证据与输出；仍不能容纳则在提交时返回容量错误，不接受注定预算不足的任务。
- search_runner.py 保存查询、初选/补选证据、诊断和模型输出。新摘要与问答不足时最多补一次；综述每篇不足时最多补一次，并保持已分配证据 ID 稳定。补检索优先匹配具体缺失项，可读取同一原始片段的不同逐字窗口。中文“创新点、贡献”会映射为英文检索术语。
- 摘要、问答的两次部分回答保留各自有引用支持的段落，综述仅填充原有空单元格。摘要、问答补检调用失败或预算不足时保留已通过校验的初次结果；最终仍按实际证据显示 partial。旧摘要没有补检预算标记时继续按原策略执行。
- 任务详情 retrieval.papers 按论文返回未覆盖维度及冻结标题；前端列出 missing_aspects 和逐篇缺失维度。缺失维度可随界面语言切换，模型生成的缺失说明保留任务输出语言，不自动翻译。
- review_store.py 同时为新单篇与综述记录调用预留和实耗；模型用量未知时保守保留预留。Worker 重启复用检查点、保持原截止时间；旧 Worker 无权写检查点或产物。
- retrieval 字段、执行事件和页面警告区分无解析文本、上下文回退、部分可回答及当前证据不足。引用继续逐字校验，不能把召回失败描述为论文全文未报告。

已有 0004 数据库升级时，停止 API 和全部 Worker，从项目根目录执行：

~~~powershell
Set-Location .\backend
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
~~~

预期 revision 为 20261115_0005；该迁移只扩展恢复约束，无需清数据。随后按 docs/terminal-operations.md 重启各进程并新建任务。已有模型地址、密钥和 .env 可继续使用；RETRIEVAL_SNAPSHOT_BYTES 不配置时使用默认值。

离线验证入口（从项目根目录开始）：

~~~powershell
Set-Location .\backend
uv run --locked python -B -m unittest discover -s tests -q
uv run --locked python -B tests/test_ownership.py --postgres
~~~

第一条运行离线测试；数据库用例默认跳过。第二条在本机 PostgreSQL 新建随机 ownership_tests 数据库并在结束时删除自己的测试库，不清理实际业务库。浏览器诊断用例为 frontend/checks/search-browser.py，测试全部拦截 API，不访问真实模型或邮箱。

验收应使用新建任务：中文询问英文论文目标/方法/结论、具体实验指标、论文未覆盖的问题，以及六篇英文论文中文比较。每项检查回答内容、逐字引用、PDF 页码、缺失维度说明、执行记录及刷新恢复。自动测试只证明代码路径和约束，真实模型回答质量需另外人工核验。
