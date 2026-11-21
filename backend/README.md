# 后端开发

后端管理账号、论文原件、研究任务和结果。网页通过 `POST /api/v1/agent-research` 提交问题，研究 Worker 将任务交给独立 Agent。课程 TACC 使用 `tcloud` 提交 CPU 作业，模型推理由百炼提供。[TACC 启动与网页验收](../tacc/TACC.md) · [HTTP API 契约](../docs/api-contract.md)

## 1. 首次启动

准备 Python 3.11+、uv 和 PostgreSQL。使用 Docker Compose 启动本地数据库时，从项目根目录执行以下命令。只在首次配置时复制模板，PowerShell 使用 `Copy-Item .env.example .env`。

```sh
cd backend
uv sync --locked
cp -n .env.example .env
docker compose up -d --wait postgres
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

使用已有 PostgreSQL 时，将 `DATABASE_URL` 指向该数据库，再执行迁移。在 `backend/.env` 填好第 8 节的派发配置和第 10 节的账号配置后，在 `backend/` 下为各 Worker 分别开一个终端。

| 进程 | 启动命令 | 用途 |
| --- | --- | --- |
| Parser | `uv run --locked python -m app.parser_worker` | 提取已上传 PDF 的标题、页数 |
| 研究 Worker | `uv run --locked python -m app.runner_worker` | 领取任务、派发、收取结果 |
| 邮件 Worker | `uv run --locked python -m app.mail_worker` | 注册验证与密码找回邮件 |
| Import Worker | `uv run --locked python -m app.import_worker` | 启用 arXiv 后下载选定版本 |

## 2. 数据库配置

API、只读论文库入口和各 Worker 共用 `DATABASE_URL`、`STORAGE_ROOT` 及后端鉴权密钥。环境变量优先于 `backend/.env`。Compose 的 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD` 和端口应与连接串一致。默认存储根目录为 `backend/runtime/storage/`，用户 PDF 保存在 `uploads/<UUID>.pdf`。[配置模板](.env.example)

## 3. 代码入口

| 目录 | 职责 |
| --- | --- |
| [api](src/app/api/) · [auth](src/app/auth/) | 业务 HTTP、账号会话与 Agent 论文库授权 |
| [papers](src/app/papers/) · [sources](src/app/sources/) | PDF 上传、元数据与 arXiv 导入 |
| [tasks](src/app/tasks/) · [agent_bridge](src/app/agent_bridge/) | 配额、幂等、租约、传输和结果校验 |
| [db](src/app/db/) · [alembic](alembic/) | 数据模型与迁移 |

## 4. 迁移维护

部署时执行第 1 节的 `alembic upgrade head` 和 `alembic check`。迁移 `20261121_0009` 区分用户预选与 Agent 在库内发现的论文。升级有数据的旧库前先备份，早于账号迁移 `20261114_0004` 的匿名业务数据需要单独处理。[数据库设计与升级边界](../docs/database-design.md#114-0004-升级重置与回退边界)

## 5. 验证与边界

主 API 的 `GET /health` 检查服务存活，`GET /ready` 检查数据库连接和迁移。运行后端回归使用以下命令。数据库用例会改写专用测试库，需按对应测试模块配置可销毁的本机 PostgreSQL 数据库。[测试目录](tests/)

```sh
uv run --locked python -B -m unittest discover -s tests -v
```

## 6. 最小业务闭环

用已验证账号登录，上传一份 PDF（上限 50 MiB），从「新建研究」提交问题。可以预选论文，或在开启检索时让 Agent 自行搜索。任务完成后从正文引用打开原 PDF 对应页。请求重试使用相同的 `Idempotency-Key`。[统一研究接口](../docs/api-contract.md#13-v3-统一研究接口2026-11-20)

## 7. 运行边界与恢复

Worker 首次领取时开始计时，重启后沿用原任务期限和派发记录。通过 `GET /api/v1/tasks/{task_id}` 查看 `agent.dispatch_id`、`remote_job_id` 与执行限额。提交回执不明时保留交换目录供 Worker 核对。部分完成的结果会保留可读正文和仍待解决的问题。[派发、恢复与结果契约](../docs/agent-backend-integration.md)

## 8. 独立 Agent 配置

在 API 和研究 Worker 中使用相同的 `TASK_RUNNER=agent`、`AGENT_DISPATCH_ENABLED=true` 和 `AGENT_TRANSPORT`。交换目录由 `AGENT_EXCHANGE_ROOT` 指定，默认是 `STORAGE_ROOT/agent-exchange`。

| `AGENT_TRANSPORT` | 运行条件 |
| --- | --- |
| `tcloud`（课程） | Worker 机器已初始化课程 SDK，计算节点可通过 `AGENT_LIBRARY_PUBLIC_URL` 的 HTTPS 地址访问论文库。Worker 使用 `AGENT_TCLOUD_MODEL_ENV_FILE` 指定的私有百炼配置为本次作业申请临时 key。 |
| `manual` | 外部执行端读取 outbox 输入，在对应 inbox 交付版本化结果。 |
| `local` | `AGENT_LOCAL_ROOT` 指向另行部署、提供 `run_dispatch.py` 的兼容执行端，`AGENT_LOCAL_PYTHON` 指向其解释器。 |
| `tacc`（历史 SSH/Slurm） | 已部署远端 helper 和配置文件，通过 `AGENT_TACC_HOST`、`AGENT_TACC_HELPER`、`AGENT_TACC_CONFIG` 指定 SSH 别名与远端绝对路径。 |

课程联调的主 API 默认运行在 `127.0.0.1:8000`。需要临时公网入口时，只将 `127.0.0.1:8001` 上的 `app.main:create_library_app` 通过 HTTPS 隧道提供给计算节点。网页使用独立的浏览器会话，作业用 Worker 签发的只读令牌。SDK 提交默认最多等待 180 秒，普通查询默认 30 秒。[课程环境、完整命令与验收记录](../tacc/TACC.md)

## 9. arXiv 搜索与导入

设置 `ARXIV_ENABLED=true`、`ARXIV_CONTACT_EMAIL` 并重启 API。从网页搜索论文，选择带明确版本的条目导入。保持 Import Worker 与 Parser 运行，可在库内查看 PDF、页数和来源。[来源接口](../docs/api-contract.md)

<a id="10-账号qq-邮件与私有数据2026-11-14"></a>

## 10. 账号与邮件

### 10.1 配置与会话

- `FRONTEND_PUBLIC_URL` 填实际浏览器来源，默认 `http://127.0.0.1:5173`。若使用其他预览端口，同步更新该值和 JSON 数组 `CORS_ORIGINS`。浏览器与 API 使用同一主机名。公网前端使用 HTTPS 和 `AUTH_COOKIE_SECURE=true`。
- `AUTH_RATE_KEY` 和 `AUTH_CSRF_KEY` 分别生成，均至少 32 字节。登录后的网页写请求使用会话 Cookie、可信 Origin 和 `X-CSRF-Token`。[账号接口](../docs/api-contract.md#2-账号与会话)
- 启用注册验证或密码找回时，配置 QQ 邮箱的 `SMTP_USERNAME`、相同的 `SMTP_FROM`、`SMTP_AUTH_CODE` 和独立 Fernet 密钥 `MAIL_OUTBOX_KEY`。SMTP 默认使用 TLS 465 端口。邮件队列中仍有待投递邮件时保持加密密钥稳定。

<a id="104-已有开发库的受控重置"></a>

### 10.2 已有开发库的受控重置

日常启停只需 `docker compose down` 和 `docker compose up -d --wait postgres`。需要清空开发库时，先停服务、备份，再用 `uv run --locked python -m app.reset_data --database <库名> --storage <存储绝对路径>` 预览受影响的记录与文件。追加 `--execute` 会执行删除。[重置工具](src/app/reset_data.py)
