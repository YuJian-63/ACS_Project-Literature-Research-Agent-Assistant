# 后端数据库开发

当前已实现 SQLAlchemy 七表模型、数据库连接配置和 Alembic 初始迁移。HTTP 接口、TaskManager、Mock Runner 和真实 Agent 尚未实现；接口规范见 `../docs/api-contract.md`。

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
```

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

下一阶段在这些基础上实现 FastAPI `/health`、`/ready`、论文上传，以及持久化 Mock 任务闭环。
