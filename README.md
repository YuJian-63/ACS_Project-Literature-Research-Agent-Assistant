# Literature Research Agent Assistant

HKUST CSIT6000V Advanced AI Computing and Systems 课程项目。用户上传 PDF、提交研究问题，再从回答中的引用打开原 PDF 对应页。Baseline 和 Retrieval Extension 可在本地或 TACC 执行，模型使用百炼 API 或独立部署的 Qwen 服务。

## Getting Started Instructions

**公网入口：** [https://8.218.149.237/](https://8.218.149.237/)。使用已部署服务时，可直接打开该地址注册、验证邮箱并登录；以下步骤用于本地运行或自行部署。

### 1. 前置条件

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows PowerShell、Linux 或 macOS；下文命令均从仓库根目录执行。 |
| 开发工具 | Git、uv、Python 3.12。后端要求 Python ≥ 3.11，独立 Agent 要求 Python 3.12。 |
| 前端 | Node.js 22.12 或更高版本及 npm；完整兼容范围见 [package.json](frontend/package.json)。 |
| 数据库 | 已启动的 Docker 和 Compose 插件，脚本使用 PostgreSQL 17；也可连接已有 PostgreSQL。 |
| 邮件 | 支持 SSL/TLS 465 端口的 SMTP 邮箱和授权码，用于注册验证；下面以 QQ 邮箱为例。 |
| 研究模型 | 百炼 API Key、对应工作空间的兼容接口地址和可用模型 ID。下面的网页研究示例在 TACC CPU 作业中调用百炼，无需申请 GPU。 |
| TACC / TCloud | 有效课程账号、已登记公钥对应的私钥、已初始化的 `tcloud` SDK，以及 SDK 可使用的 Python 3.12 执行环境。仅启动网页、注册和上传 PDF 时无需集群。 |
| 网络与端口 | 能下载依赖和镜像、连接 SMTP 及 TACC；Worker 和计算节点均能访问百炼，计算节点能通过 HTTPS 访问论文库。本地端口 `5173`、`8000` 和默认数据库端口 `55432` 未被占用；临时论文库入口另用 `8001`。 |

首次安装需要联网，真实研究会产生模型 API 费用。请自行准备密钥，不要将私有 `.env` 提交到 Git。

### 2. 获取代码并初始化

```sh
git clone https://github.com/YuJian-63/ACS_Project-Literature-Research-Agent-Assistant.git
cd ACS_Project-Literature-Research-Agent-Assistant
git rev-parse HEAD
```

记录提交 SHA，便于确认运行版本；已有工作副本可跳过克隆。按系统选择一条初始化命令：

| 系统 | 命令 |
| --- | --- |
| Windows PowerShell | `.\scripts\service-windows.ps1 init` |
| Linux | `bash scripts/service-linux.sh init` |
| macOS | `bash scripts/service-macos.sh init` |

初始化会安装前后端依赖、创建缺失的 `backend/.env`、补齐三个独立安全密钥、启动数据库并执行迁移。首次配置暂时关闭研究派发、arXiv 和评分；已有非空配置和密钥保留。成功时输出：

```text
Initialization complete. Run start to launch the services.
```

Windows 若阻止执行脚本，可用 `powershell -ExecutionPolicy Bypass -File .\scripts\service-windows.ps1 init`，启动时将 `init` 换成 `start`。使用已有 PostgreSQL 时，先在 `backend/.env` 配置 `DATABASE_URL`，再为 **init 和 start** 都添加 `--external-db`，Windows 对应 `-ExternalDb`。

### 3. 配置注册邮件和 TCloud 研究

使用运行后端 Worker 的同一系统账号，先按 [TCloud 初始化说明](tacc/README.md#常用-tcloud-命令)配置课程账号与私钥，执行 `tcloud init` 和 `tcloud env ls`。确认有 SDK 可用的 Python 3.12 环境；以下以 `acs-network-probe` 为例，它不会由本地初始化脚本创建。集群环境的目录权限和 SDK 路径要求也需满足。

编辑生成的私有 `backend/.env`，更新以下字段，保留生成的 `AUTH_RATE_KEY`、`AUTH_CSRF_KEY` 和 `MAIL_OUTBOX_KEY`：

```dotenv
FRONTEND_PUBLIC_URL=http://127.0.0.1:5173
CORS_ORIGINS=["http://127.0.0.1:5173"]
AUTH_COOKIE_SECURE=false

SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USERNAME=your-mailbox@qq.com
SMTP_FROM=your-mailbox@qq.com
SMTP_AUTH_CODE=replace-with-your-smtp-authorization-code

TASK_RUNNER=agent
AGENT_DISPATCH_ENABLED=true
AGENT_TRANSPORT=tcloud
AGENT_TCLOUD_CLI=tcloud
AGENT_TCLOUD_ENV_NAME=acs-network-probe
AGENT_TCLOUD_MODEL_ENV_FILE=../agent/.env
AGENT_LIBRARY_PUBLIC_URL=https://your-library-host.example
AGENT_PERSIST=false
ARXIV_ENABLED=false
EVALUATION_ENABLED=false
```

`SMTP_USERNAME` 与 `SMTP_FROM` 必须相同；`SMTP_AUTH_CODE` 是 SMTP 授权码。环境名替换为自己的可用环境；论文库 HTTPS 地址在下一步填写，不能使用示例域名或集群无法访问的 `127.0.0.1`。

首次将 [agent/.env.example](agent/.env.example) 复制为 `agent/.env`，已有文件则直接编辑。在该私有文件中填写：

```dotenv
MODEL_PROVIDER=bailian
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen3.8-27b
BAILIAN_API_KEY=replace-with-your-bailian-api-key
```

地址和模型 ID 应与实际账号匹配，不能将 API Key 填入地址字段。Linux/macOS 需执行 `chmod 600 agent/.env`，文件须属于 Worker 账号；Worker 读取该文件，为每个作业申请百炼临时密钥。此路径由作业准备 Agent 依赖，无需安装本机 Agent 虚拟环境。示例使用 Baseline 和已上传论文，不需要 Tavily、Embedding 或 Agent 独立持久化数据库。

前端默认使用同源 API，无需新建 `frontend/.env.local`；已有配置时核对代理仍指向 `127.0.0.1:8000`。更多字段见 [后端配置](backend/README.md#配置与账号)和 [Agent 配置](agent/README.md)。

### 4. 提供计算节点可访问的论文库

已有公网 HTTPS 入口且已代理该后端论文库接口时，将其源地址写入 `AGENT_LIBRARY_PUBLIC_URL`，可跳过本节其余命令。本地开发没有公网入口时，先安装 `cloudflared`，再另开终端，从仓库根目录启动只读论文库 API：

```sh
cd backend
uv run --locked uvicorn app.main:create_library_app --factory --host 127.0.0.1 --port 8001
```

再另开终端建立临时 HTTPS 隧道：

```sh
cloudflared tunnel --url http://127.0.0.1:8001
```

将输出的 `https://...trycloudflare.com` 地址写入 `backend/.env` 的 `AGENT_LIBRARY_PUBLIC_URL`，只填源地址，不添加 API 路径。两个终端都保持运行，论文库 API 必须使用与主 API 相同的数据库、存储和鉴权密钥。重建隧道后地址可能变化，需更新配置并重启研究 Runner。各系统 `service-* start` 不会自动启动论文库入口或隧道；Bash 环境也可按 [TACC 一键启动流程](tacc/TACC.md#本机一键启动)统一管理。

### 5. 启动并检查服务

| 系统 | 命令 |
| --- | --- |
| Windows PowerShell | `.\scripts\service-windows.ps1 start` |
| Linux | `bash scripts/service-linux.sh start` |
| macOS | `bash scripts/service-macos.sh start` |

保持终端运行。按上述配置，启动器会运行 API、Parser、Mail、Agent Runner 和 Vite，输出应包含：

```text
Workers: parser, mail, runner
Open http://127.0.0.1:5173 . Ctrl+C stops this launcher's services; PostgreSQL is kept.
```

另开终端检查 API；Windows 将 `curl` 写成 `curl.exe`：

```sh
curl --noproxy '*' -fsS http://127.0.0.1:8000/health
curl --noproxy '*' -fsS http://127.0.0.1:8000/ready
```

两次请求应依次返回 `{"status":"ok"}` 和 `{"status":"ready"}`。这些接口检查存活、数据库和迁移；下面的示例继续验证注册邮件、研究执行和引用链路。

### 6. 最小端到端示例

使用仓库提供的两页合成测试论文 [Orchid Calibration Report.pdf](<frontend/checks/fixtures/Orchid Calibration Report.pdf>)，无需另行下载论文：

1. 打开 `http://127.0.0.1:5173`，注册、通过邮件验证，再登录。用户名为 3–32 位英文字母、数字或下划线，不能使用 `Admin` 等系统保留名；登录时保持注册时的大小写。
2. 在论文库上传该 PDF，等待状态变为 `ready`，确认可以打开原始 PDF。
3. 新建研究并选中这篇论文，模型来源选择 **百炼 API**，研究模式选择 **Baseline**，关闭追加检索，填写下面的问题后提交：

   ```text
   只查我的论文库，《Orchid Calibration Report》最终校准记录的校验标签是什么？请引用第二页原文。
   ```

4. 在研究记录中等待完成，打开答案并点击一处引用，核对证据及 PDF 页码。

**预期结果：** 论文状态为 `ready`、页数为 2；研究最终状态为 `succeeded`，答案包含 `LUMEN-472`，引用能打开该 PDF 的第 2 页。在已登录浏览器的开发者工具中，创建请求 `POST /api/v1/agent-research` 返回 `202`，随后 `GET /api/v1/agent-research/{task_id}` 包含 `status: "succeeded"` 和非空 `result`。任务 UUID、回答措辞和耗时会变化，不要求逐字匹配。

任务持续排队时检查 Runner 和 `tcloud ps`，上传未变为 `ready` 时检查 Parser，未收到邮件时检查 Mail 和垃圾邮件箱。日志在 `backend/runtime/services/` 的 `api.log`、`parser.log`、`mail.log`、`runner.log`。仅验证账号和 PDF 功能时，可先设 `AGENT_DISPATCH_ENABLED=false`，跳过集群、模型及隧道配置；此时不能完成研究示例。详见 [启动与联调](docs/service_launch.md)。

### 7. 可选：启动 DeepSeek 评分 Worker

需要对研究结果评分时，在私有 `backend/.env` 中单独配置评分模型：

```dotenv
EVALUATION_ENABLED=true
EVALUATION_BASE_URL=https://api.deepseek.com
EVALUATION_MODEL=replace-with-an-available-deepseek-model-id
EVALUATION_API_KEY=replace-with-your-deepseek-api-key
```

评分凭据与 Agent 研究模型配置独立。使用上面的启动脚本时，先按 Ctrl+C 停止本次服务，再重新执行对应系统的 `start` 命令，API 和研究 Worker 会重新加载配置，评分 Worker 也会自动启动。沿用快速示例的其他设置时，输出应包含 `Workers: parser, mail, runner, evaluation`，评分日志位于 `backend/runtime/services/evaluation.log`。

启用后自动评分新交付的研究结果，不会扫描历史任务；历史结果需主动申请评分。评分失败不会覆盖研究正文，评分状态和五维结果可从任务详情接口获取。

若按手动方式管理各进程，修改配置后重启 API 和研究 Worker，再另开终端执行：

```sh
cd backend
uv run --locked python -m app.evaluation_worker
```

启动脚本已管理评分 Worker 时，无需再手动运行该命令。ECS 使用独立的 `acs-evaluation.service`，安装与启停见 [后端评分服务说明](backend/README.md#deepseek-evaluation)。

## Detailed Instructions

### 项目结构与数据流

浏览器通过 API 管理论文和任务，后端将输入交给独立 Agent，再保存答案、引用和指标。PostgreSQL 保存业务数据，后端文件目录保存 PDF 原件，浏览器不直接持有模型密钥。

| 目录 | 职责与说明 |
| --- | --- |
| [frontend/](frontend/README.md) | React / TypeScript 研究工作台，提供账号、论文库、任务详情及原文证据界面。 |
| [backend/](backend/README.md) | FastAPI、PostgreSQL、数据库迁移，以及解析、邮件和研究等后台 Worker。 |
| [agent/](agent/README.md) | Baseline 和 Retrieval Extension，负责阅读、检索、模型调用和带引用的回答。见[研究工作流与流程图](agent/README.md#agent-workflow)、[任务与结果接口](agent/README.md#任务与结果接口)和[消融实验复现](agent/README.md#消融实验复现)。 |
| [tacc/](tacc/README.md) | 课程 SDK、环境配置与探测脚本；[run_job.py](tacc/research/run_job.py) 读取任务清单并调用 Agent。 |
| [model-server/](model-server/README.md) | 独立运行在 TACC GPU 节点上的课程 Qwen 模型服务及遥测采集。 |
| [scripts/](docs/service_launch.md#按系统使用脚本) | 各系统本地启动器、TACC 联调和 ECS 服务入口。 |
| [ops/deploy/](ops/deploy/) | ECS 发布脚本与校验；[工作流](.github/workflows/deploy-ecs.yml)由推送 `main` 触发。 |
| [docs/](docs/) | [API 契约](docs/api-contract.md)、[数据库设计](docs/database-design.md)、[服务启动](docs/service_launch.md)和 [Proposal](docs/Proposal.md)。 |

### 其他运行方式

- **手动启动 / 外部数据库：** 见 [服务启动说明](docs/service_launch.md)。启动器的 `check` 仅检查配置和工具，不验证模型、邮件或集群连通性。
- **独立本地 Agent：** 按 [Agent 文档](agent/README.md)运行 CLI。网页 `local` 派发要求兼容的 `run_dispatch.py` 入口，当前 `agent/` 未提供该适配器，不能仅切换 `AGENT_TRANSPORT=local` 来替代上述 TCloud 链路。
- **TACC / TCloud：** 需要课程账号、已登记的 SSH 公钥、初始化后的 SDK、可用执行环境，以及计算节点可访问的论文库 HTTPS 地址。按 [首次配置](tacc/TACC.md#首次配置从新账号注册到网页研究)操作；本机可用 `./scripts/local-research configure` 和 `./scripts/research up`，没有固定公网入口时按 [隧道流程](tacc/TACC.md#本机一键启动)配置。
- **TACC 模型：** 先按 [模型服务说明](model-server/README.md)启动 GPU 服务，再配置 Agent 接口。Agent 作业必须能访问该地址；集群内网地址不保证能从 ECS 或个人电脑直接访问。模型服务和 Agent CPU 作业分别管理。
- **已部署 ECS：** 使用已安装的 systemd 服务、Nginx 和 HTTPS；在有权限的账号下执行 `./scripts/research up`。设置计算节点可达的 `AGENT_LIBRARY_PUBLIC_URL`，通过自动部署流程更新代码。本地开发脚本不会安装这些生产设施。

### 配置、数据与运行边界

- 配置样例分别位于 `backend/.env.example`、`agent/.env.example` 和 `frontend/.env.example`。API 和后端 Worker 共用数据库、存储及账号密钥；环境变量优先于 `.env`。`VITE_*` 会进入浏览器，只能放公开配置。
- 网页 arXiv 搜索/导入需开启 `ARXIV_ENABLED`、填写联系邮箱并运行 Import Worker；Agent 外部搜索另需 Tavily。Retrieval Extension 的 Embedding 和可选开关见 [Agent 文档](agent/README.md)。
- 后端任务详情接口提供 DeepSeek 五维评分、Agent 调用与 Token 统计、模型服务性能及缓存指标，字段和获取方式见 [任务指标契约](backend/README.md#任务指标与前端接入)。模型服务未返回的指标会标为不可用；GPU 为采样快照，不能当作任务平均利用率。
- 单份上传/导入 PDF 上限为 50 MB，最多预选 20 篇论文；公网反向代理还需预留 multipart 开销。步数、时限、输出 Token 和用户额度见 [派发与预算](backend/README.md#agent-dispatch)。全站研究并发数可在模型管理中设为 1–4，所有账号共用。
- PDF、数据库卷和日志不会随 Git 克隆迁移。Ctrl+C 停止本次启动的本地服务，数据库保留；停止数据库需从 `backend/` 执行 `docker compose stop postgres`。重新初始化或迁移前备份已有数据；修改 `.env` 不会重设已有数据库卷的账号密码。
- 示例验证小规模功能链路。真实论文的文本提取、上下文长度、模型输出和网络条件会影响回答及引用，扫描 PDF 可能缺少可用文本。TACC 运行时间还受排队及资源影响。模型和 SMTP 凭据需要使用者自行准备。

### Evaluation
