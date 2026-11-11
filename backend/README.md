# 后端开发

当前已实现数据库基础设施及 MVP-0：FastAPI 健康检查、PDF 上传/读取、论文和任务分页、幂等提交、事件轮询、产物查询、独立 Mock Worker，以及超时/租约恢复。尚未接入真实 PDF 解析器或 Agent；接口规范见 `../docs/api-contract.md`。

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

API 和 Worker 必须使用同一个数据库及 STORAGE_ROOT。仅启动 API 时，提交的任务会持久化为 queued，不会执行；后续启动 Worker 后才会被领取。API 不依赖 FastAPI BackgroundTasks 执行任务，也不自动建表或迁移。

浏览器访问 `http://127.0.0.1:8000/docs` 使用自动生成的交互式接口文档，`/openapi.json` 为机器可读契约。先检查 `/health` 和 `/ready`，再上传 PDF、提交任务并轮询结果。停止 API 和 Worker 不会删除数据库和论文文件。

Linux/macOS 将复制命令替换为 `cp .env.example .env`。其他命令相同。迁移成功后的 revision 是 `20261110_0001`；数据库包含七张业务表和 Alembic 自己的版本表。`alembic check` 正常输出 `No new upgrade operations detected.`。

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

不加 `--sql` 的 `alembic downgrade base` 会实际删除七张业务表及其中数据，只适用于可丢弃开发库。停止本地数据库可执行 `docker compose down`，该命令保留命名数据卷。

## 5. 已执行验证与边界

2026-11-10 使用临时脚本完成：

- 12 项配置、密码脱敏、凭据查询参数拒绝、环境优先级、延迟连接、模型编译、迁移版本图、模板与离线迁移检查通过。
- 参考 DDL、迁移 SQL、ORM SQL 的数据库目录对照一致：85 个业务字段，主键/外键/CHECK/唯一约束及索引一致。
- 在 PostgreSQL 18.6 / PGlite 0.5.16 上，迁移和 ORM 生成的 SQL 分别通过原有 68 项约束验证。
- psycopg 经临时本机 socket 执行在线升级、重复升级、ORM 读写、可空 JSONB 显式 None、事务回滚、幂等键冲突、Alembic 无漂移检查、降级与重新升级，18 项检查通过。
- Docker Compose 配置解析通过；本机 Docker 守护进程未运行，未实际启动 PostgreSQL 容器。

PGlite socket 不等价于原生 PostgreSQL 多连接模型。PostgreSQL 17+ 上的安装启动、真实多 Worker 竞争、锁/超时及后续 HTTP 集成仍需在相应环境验收。当前没有引入测试框架；临时校验脚本位于忽略的 runtime 目录，不是发布的后端运行依赖。

2026-11-11 增量验证：14 组 HTTP/数据库集成检查通过，覆盖统一错误与跨域头、PDF 头/文件名/精确 20 MiB 上限、重复上传、字面搜索、来源与预算校验、幂等规范化/重放/冲突、唯一冲突后的新事务重查、无 Worker 保持 queued、事件游标、Mock 产物、原子回滚、失联/超时与旧 Worker 写入拒绝、文件写入失败及不确定提交补偿。此前 12 项数据库基础校验也通过回归。

另以独立 Uvicorn 和 Worker 进程完成真实 HTTP 冒烟验证：排队后重启 API 仍可查询；独立 Worker 消费并生成模拟产物；终态幂等重放；API 重启时恢复失联任务；文件持久化读取。验证使用 PostgreSQL 18.6 / PGlite 0.5.16，并为多进程启用 socket 连接复用。这不等价于原生 PostgreSQL 多连接事务：本机 Docker 守护进程仍未运行，PostgreSQL 17+ 上真实双 Worker 竞争、并发幂等竞争及锁行为仍待验收。临时验证脚本在忽略的 runtime 目录；httpx 仅是开发验证依赖。

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
- 上传实际文件最大 20 MiB，分块统计大小并计算 SHA-256；额外限制 multipart 整体为 20 MiB + 64 KiB，避免解析阶段无限写临时文件。只检查 PDF 文件头，尚不保证内容可解析；论文保持 uploaded，page_count/parser_version 为 null。
- Mock Worker 领取事务使用行锁及 SKIP LOCKED，租约 60 秒，独立心跳 20 秒；开始时间后的 timeout_seconds 到期优先标为 TASK_TIMEOUT，否则租约到期标为 WORKER_LOST。不自动重跑失联任务，旧 Worker 不能覆盖失败结果。
- 模拟产物明确标注未分析论文、引用为空、比较表为 null。原子写入产物、成功状态与事件；真实研究结论与证据校验留待真实 Runner 阶段实现。
- 上传在明确未提交时清除本次临时/目标文件；提交结果不确定时保留文件并新建会话核对。暂时无法确认返回 503，日志仅记录 paper_id；请先查询论文列表，不要直接删除 uploads 下文件。当前没有自动孤儿文件清理命令，人工核对需先确认原事务已结束，并保留宽限期及备份。
- 默认上传目录和临时验证产物均被 Git 忽略；自定义 STORAGE_ROOT 应放在仓库外或自行确认 ignore 规则。停止所有服务时不会即时恢复任务，下一次 API/Worker 启动时恢复。

下一阶段可开发前端论文库、上传交互和任务详情/轮询页，再接入真实解析与 Agent。
