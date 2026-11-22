# 本地启动与联调

首次准备开发环境需要 Docker、uv 和 Node.js。已有前后端时，从网页提交课程集群作业见 [TACC 联调说明](../tacc/TACC.md)。

## 配置和迁移

从仓库根目录进入 `backend/`，运行 `uv sync --locked`。首次配置时用 `.env.example` 创建 `.env`。

| 系统 | 在 `backend/` 执行 |
| --- | --- |
| Windows PowerShell | `if (!(Test-Path .env)) { Copy-Item .env.example .env }` |
| macOS / Linux | `test -f .env || cp .env.example .env` |

在 `.env` 中设置 PostgreSQL 用户、库名、密码和端口，让 `DATABASE_URL` 与它们一致。API 和 Worker 共用数据库、`STORAGE_ROOT` 和鉴权配置。注册、重发验证邮件和找回密码还需要配置 SMTP 和邮件密钥。[后端配置](../backend/README.md)

在 `backend/` 执行以下命令。若原数据库使用自定义 Compose 项目名，继续使用 `docker compose -p 原项目名` 访问同一数据卷。

```sh
docker compose up -d --wait postgres
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

本分支的迁移 head 为 `20261122_0013`。`alembic current` 应与 `alembic heads` 一致，`alembic check` 应报告无新增迁移操作。[迁移维护](../backend/README.md#4-迁移维护)

## 启动服务

按需打开独立终端，每个后端终端都在 `backend/` 执行对应命令。

| 服务 | 命令 | 用途 |
| --- | --- | --- |
| API | `uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000` | 网页接口、账号与论文库 |
| Parser Worker | `uv run --locked python -m app.parser_worker` | 提取上传或导入 PDF 的标题、页数等元数据 |
| Mail Worker | `uv run --locked python -m app.mail_worker` | 发送验证及找回密码邮件 |
| Import Worker | `uv run --locked python -m app.import_worker` | 启用 arXiv 后下载导入的论文 |

前端在仓库根目录执行 `npm --prefix frontend ci` 安装依赖，再运行 `npm --prefix frontend run dev`。PowerShell 可用 `npm.cmd`。默认访问 [本地网页](http://127.0.0.1:5173)。[前端启动说明](../frontend/README.md#本地开发)

<a id="agent-第-2-阶段远程作业入口"></a>

## 启动研究 Worker

新研究任务使用 `TASK_RUNNER=agent`。课程 TACC 使用 `AGENT_TRANSPORT=tcloud`。先配置课程 SDK、计算节点可访问的论文库 HTTPS 地址和百炼凭据，再启用 `AGENT_DISPATCH_ENABLED=true`。API 和 Worker 读取同一份配置，在 `backend/` 的独立终端启动 Worker。[TACC 配置与作业检查](../tacc/TACC.md)

```sh
uv run --locked python -m app.runner_worker
```

## 验收与排查

| 要验证什么 | 操作与判断 |
| --- | --- |
| API 和数据库 | 打开 `http://127.0.0.1:8000/health` 和 `/ready`，响应的 `status` 字段应分别为 `ok` 和 `ready`。 |
| 论文库 | 登录后上传一篇 PDF，待解析完成，在网页打开原文并核对页数。 |
| 研究闭环 | 提交有明确原文依据的问题，在研究记录中打开结果，点击引用核对 PDF 页。检查自主检索时，将预选论文留空，网页会随请求启用搜索。 |
| 任务长时间排队 | 核对 API 和 Worker 的派发配置、Worker 日志及任务详情的 `agent.remote_job_id`。获得作业号后用 `tcloud ps -j JOBID` 查询，最终以回传的结果和任务状态为准。 |

后端测试与数据库隔离要求见[后端验证说明](../backend/README.md#5-验证与边界)，前端构建、单元及浏览器检查见[前端 README](../frontend/README.md)。本地服务可在各自终端按 Ctrl+C 停止，使用 `docker compose stop postgres` 停止数据库并保留数据卷。

## PDF 运维

- 单个 PDF 上限为 50 MiB。使用 Nginx 时可设置 `client_max_body_size 51m` 为 multipart 上传留出空间，运行 `nginx -t` 通过后再重载配置。
- 已就绪论文需要补提取标题时，在 `backend/` 运行 `uv run --locked python -m app.papers.refresh_titles` 预览。确认候选记录后，用同一命令加 `--execute` 保存更新。
