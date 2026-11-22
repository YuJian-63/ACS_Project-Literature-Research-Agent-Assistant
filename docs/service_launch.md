# 前后端启动与联调

本指南覆盖首次配置、启动与检查。[后端配置](../backend/README.md) · [前端构建与代理](../frontend/README.md) · [TACC 与模型](../tacc/TACC.md)

## 按系统使用脚本

先安装 `uv`、满足 `frontend/package.json` 要求的 Node.js，以及 Docker 和 Compose 插件；Windows/macOS 可用 Docker Desktop，运行前启动 Docker。脚本适用于本地开发，统一使用 `http://127.0.0.1:5173`。在仓库根目录执行：

| 系统 | 首次初始化 | 启动服务 |
| --- | --- | --- |
| Windows PowerShell | `.\scripts\service-windows.ps1 init` | `.\scripts\service-windows.ps1 start` |
| Linux | `bash scripts/service-linux.sh init` | `bash scripts/service-linux.sh start` |
| macOS | `bash scripts/service-macos.sh init` | `bash scripts/service-macos.sh start` |

Windows 若提示禁止运行脚本，可仅对本次进程放行：`powershell -ExecutionPolicy Bypass -File .\scripts\service-windows.ps1 init`；启动时将最后的 `init` 换成 `start`。

- **init**：uv 安装后端依赖，安装前端依赖，创建缺失的 `backend/.env` 和三个独立安全密钥，启动 Compose PostgreSQL，执行 `alembic upgrade head`。更新代码后也可重跑；已有数据库先备份，脚本不会删除数据卷或重置数据库密码。
- **start**：确保 Compose 数据库运行，启动 API、Parser、Vite；按配置启动 Mail、Agent Runner、arXiv Import 和 Evaluation Worker。等待 API 和前端代理的 `/ready` 后显示访问地址。依赖或表结构变化时先重跑 `init`。
- **check**：将命令末尾替换为 `check`，仅检查配置和本机工具，不连接数据库、SMTP、模型或 TACC。

首次生成的私有 `.env` 使用本地 HTTP Cookie，暂时关闭 Agent 派发、arXiv 和评分；数据库值沿用样例。已有 `.env` 的非空配置和密钥保持不变，仅补齐缺失密钥；若已有配置不完整或仍使用 HTTPS，脚本会提示需要调整的字段。环境变量仍按后端规则优先于 `.env`，不要在终端保留过期配置。

**注册/重置密码前**，在 `backend/.env` 填写 `SMTP_HOST/PORT/USERNAME/AUTH_CODE/FROM`，重新 `start` 即会带上 Mail Worker。脚本不索取或输出授权码；邮箱未配置时，网页和 API 可启动，但注册验证邮件无法发送。研究、导入、评分的凭据见下文“按需启用功能”；脚本不会初始化 TACC 账号、部署模型或配置 Agent 自身环境。现有 TACC 隧道联调仍用 [课程启动流程](../tacc/TACC.md#本机一键启动)。

使用已有 PostgreSQL 时，先在 `backend/.env` 填好 `DATABASE_URL`，在 **init 和 start 两次命令**后都加 `--external-db`（Windows 使用 `-ExternalDb`），脚本便不调用 Docker。默认 Compose 模式会核对连接串与 `POSTGRES_*` 是否一致；改 `.env` 不会改变已有数据卷中的账号密码。

服务日志追加写入 `backend/runtime/services/` 下的 `api.log`、`parser.log`、`web.log` 及可选 Worker 日志。按 Ctrl+C 停止本次启动的服务，单个服务退出也会回收同批进程；数据库继续运行并保留数据。停止数据库可在 `backend/` 执行 `docker compose stop postgres`。端口冲突时先检查原进程，脚本不会终止已有服务。

**现有 ECS 继续使用 systemd 和自动部署流程**；这里的开发脚本不会安装 Nginx、签发证书、创建 systemd 单元或修改线上 HTTPS 配置。需要逐项排查时使用下面的手动命令。

### 旧入口兼容

`./scripts/local-research configure` 仍用于 TACC 专用配置：首次按当前样例的数据库名、用户和端口生成连接串及随机密码，补齐登录与邮件密钥，使用本地 HTTP Cookie；已有连接、密钥、后端 Tavily Key 和评分配置保留。此流程会启用 TACC 与 arXiv，前端依赖仍需按课程指南安装。随后 `up` 会在启动服务前执行数据库迁移（已有数据库先备份），并按配置启动评分 Worker；日志可用 `./scripts/local-research logs evaluation` 查看。新旧启动器共用进程锁，修改配置前先停止当前启动器。

ECS 的 `./scripts/research up` 按配置选择 Worker；只有 TACC/TCloud 派发开启时才要求公网论文库地址，评分开启但缺少对应 systemd 单元时会提前报错。自动部署会将**已经运行的** `acs-evaluation.service` 纳入停止、重启和失败处理。部署脚本更新到 ECS 后，需以 root 在仓库根目录执行 `bash ops/deploy/setup-ecs.sh`，重新安装 `/usr/local/sbin/acs-deploy-release`，现有入口不会因源码更新自行替换。该安装步骤不重启应用服务。

## 1. 环境与配置

需要 Python 3.11+、uv、Node.js `^20.19.0 || >=22.12.0`、PostgreSQL 17；下文用 Docker Compose 启动数据库。独立 Agent 另用 Python 3.12。

从仓库根目录安装后端依赖：

```sh
cd backend
uv sync --locked
```

首次从 `.env.example` 创建 `backend/.env`，已有文件保留：

| 终端 | 在 `backend/` 执行 |
| --- | --- |
| PowerShell | `if (!(Test-Path .env)) { Copy-Item .env.example .env }` |
| macOS / Linux | `test -f .env || cp .env.example .env` |

样例数据库名、用户名、密码均为 `literature_assistance_system`，宿主机端口 `55432`；修改时同步 `DATABASE_URL` 与 `POSTGRES_DB/USER/PASSWORD/PORT`。使用现有 PostgreSQL 则跳过 Compose。

样例启用了部分可选功能；先运行本地账号和论文库时，在私有 `.env` 覆盖：

```dotenv
FRONTEND_PUBLIC_URL=http://127.0.0.1:5173
CORS_ORIGINS=["http://127.0.0.1:5173"]
AUTH_COOKIE_SECURE=false
AGENT_DISPATCH_ENABLED=false
ARXIV_ENABLED=false
EVALUATION_ENABLED=false
```

按 [账号配置](../backend/README.md#配置与账号)生成独立的 `AUTH_RATE_KEY/AUTH_CSRF_KEY/MAIL_OUTBOX_KEY`，填写 SMTP 邮箱及授权码。API 和 Worker 共用配置、数据库与存储；私有 `.env` 不提交 Git。

## 2. 数据库与迁移

在 `backend/` 执行：

```sh
docker compose up -d --wait postgres
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic heads
uv run --locked alembic check
```

`current` 应与 `heads` 一致，`check` 无新增操作。已有数据先备份；沿用原 Compose 项目名，仅改 `.env` 不会重设已有库账号或密码。[迁移边界](database-design.md#数据库迁移)

## 3. 启动后端

每条命令在独立的 `backend/` 终端持续运行：

| 服务 | 命令 | 用途 |
| --- | --- | --- |
| API | `uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000` | 账号、论文和任务接口 |
| Parser | `uv run --locked python -m app.parser_worker` | PDF 标题、页数及解析状态 |
| Mail | `uv run --locked python -m app.mail_worker` | 验证和找回密码邮件 |

## 4. 启动前端

另开终端，在仓库根目录运行；PowerShell 可用 `npm.cmd`：

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

访问 `http://127.0.0.1:5173`，使用同一主机名。Vite 将 `/api`、`/health`、`/ready` 代理到 `http://127.0.0.1:8000`；后端改端口时同步 `frontend/.env.local` 的 `API_PROXY_TARGET`。`VITE_*` 会进入浏览器，不可填密钥。

生产用 `npm --prefix frontend run build`，由 Nginx 托管 `frontend/dist/` 并代理 API。HTTPS 部署同步前端来源、CORS 和 `AUTH_COOKIE_SECURE=true`；代理上传限制须覆盖 50 MB PDF 及 multipart 开销。

## 5. 按需启用功能

补齐配置后重启 API 及受影响 Worker，再在独立的 `backend/` 终端运行：

| 功能 | 配置与前提 | 命令 |
| --- | --- | --- |
| Agent 研究 | `TASK_RUNNER=agent`、`AGENT_DISPATCH_ENABLED=true`；设 `AGENT_TRANSPORT=local` 并准备 Agent 环境，或设 `tcloud` 并初始化 SDK、配置可达的论文库 HTTPS 地址及模型。 | `uv run --locked python -m app.runner_worker` |
| arXiv 搜索/导入 | `ARXIV_ENABLED=true`、`ARXIV_CONTACT_EMAIL`；解析仍需 Parser。 | `uv run --locked python -m app.import_worker` |
| DeepSeek 评分 | `EVALUATION_ENABLED=true` 及有效 `EVALUATION_BASE_URL/MODEL/API_KEY`，与研究模型独立。 | `uv run --locked python -m app.evaluation_worker` |

Agent 外部搜索另需后端 `TAVILY_API_KEY`，与网页 arXiv 开关独立。TACC 不能通过 ECS/开发机的 `127.0.0.1` 访问论文库，`AGENT_LIBRARY_PUBLIC_URL` 须为计算节点可达的 HTTPS 来源。[传输配置](../backend/README.md#agent-dispatch) · [隧道与一键联调](../tacc/TACC.md#本机一键启动)

## 6. 检查与停止

| 检查 | 操作与预期 |
| --- | --- |
| 存活/就绪 | `http://127.0.0.1:8000/health` 返回 `{"status":"ok"}`，`/ready` 返回 `{"status":"ready"}`；不代表模型或全部 Worker 就绪。 |
| 账号/论文 | 注册、邮件验证、登录；上传 PDF，待 `ready` 后打开原件。 |
| 研究 | 提交问题，查看结果与引用页；排队异常查 Worker 日志、`/api/v1/tasks/{id}` 的 `agent.remote_job_id` 和 `tcloud ps -j JOBID`。 |
| 评分 | 启用后新交付结果自动排队；历史结果或失败版本可主动申请/重试，见 [指标接口](api-contract.md#8-任务指标与评分)。 |

端口冲突先检查现有进程，改端口后同步代理。测试命令见 [后端验证](../backend/README.md#验证与排障)、[前端验证](../frontend/README.md#验证)。

Ctrl+C 停止本地进程；在 `backend/` 用 `docker compose stop postgres` 保留数据卷。ECS 用 systemd 管理：根目录 `./scripts/research up` 启动已配置的服务，评分开启时会启动已安装的 `acs-evaluation.service`。自动部署见 [工作流](../.github/workflows/deploy-ecs.yml)和 [部署脚本](../ops/deploy/deploy-ecs.sh)。
