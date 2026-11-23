# Literature Research Agent Assistant

HKUST CSIT6000V Advanced AI Computing and Systems 课程项目。用户上传 PDF、arXiv搜索、导入论文，提交研究问题，接收问题回答。Baseline 和 Retrieval Extension 可在本地或 TACC 执行，模型使用百炼 API 或独立部署的 Qwen 服务。

## Getting Started Instructions

**公网入口：** [https://8.218.149.237/](https://8.218.149.237/)。已实现将系统部署到云服务器，访问公网网址即可访问服务，使用已部署服务时，可直接打开该地址注册、验证邮箱并登录。以下步骤用于本地运行或自行部署。

### 1. 前置条件

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows PowerShell、Linux 或 macOS；下文命令均从仓库根目录执行。 |
| 开发工具 | Git、uv、Python 3.12。后端要求 Python ≥ 3.11，独立 Agent 要求 Python 3.12。 |
| 前端 | Node.js 22.12 或更高版本及 npm；完整兼容范围见 [package.json](frontend/package.json)。 |
| 数据库 | 已启动的 Docker 和 Compose 插件，脚本使用 PostgreSQL 17；也可连接已有 PostgreSQL。 |
| 邮件 | 支持 SSL/TLS 465 端口的 SMTP 邮箱和授权码，用于注册验证；下面以 QQ 邮箱为例。 |
| 研究模型 | 百炼 API Key、对应工作空间的兼容接口地址和可用模型 ID。下面的网页研究示例在 TACC CPU 作业中调用百炼，无需申请 GPU。 |
| 评分模型 | 使用 Deepseek-Flash 用于任务评分，需要配置相关数据。 |
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
| [agent/](agent/README.md) | Baseline 和 Retrieval Extension，负责阅读、检索、模型调用和带引用的回答。 |
| [tacc/](tacc/README.md) | 课程 SDK、环境配置与探测脚本；[run_job.py](tacc/research/run_job.py) 读取任务清单并调用 Agent。 |
| [model-server/](model-server/README.md) | TACC 课程 Qwen 原版服务、[优化版](model-server/server-opt/README.md)、遥测及模型服务实验。 |
| [scripts/](docs/service_launch.md#按系统使用脚本) | 各系统本地启动器、TACC 联调和 ECS 服务入口。 |
| [ops/deploy/](ops/deploy/) | ECS 发布脚本与校验；[工作流](.github/workflows/deploy-ecs.yml)由推送 `main` 触发。 |
| [docs/](docs/) | [API 契约](docs/api-contract.md)、[数据库设计](docs/database-design.md)、[服务启动](docs/service_launch.md)和 [Proposal](docs/Proposal.md)。 |

### 其他运行方式

- **手动启动 / 外部数据库：** 见 [服务启动说明](docs/service_launch.md)。启动器的 `check` 仅检查配置和工具，不验证模型、邮件或集群连通性。
- **独立本地 Agent：** 按 [Agent 文档](agent/README.md)运行 CLI。网页 `local` 派发要求兼容的 `run_dispatch.py` 入口，当前 `agent/` 未提供该适配器，不能仅切换 `AGENT_TRANSPORT=local` 来替代上述 TCloud 链路。
- **TACC / TCloud：** 需要课程账号、已登记的 SSH 公钥、初始化后的 SDK、可用执行环境，以及计算节点可访问的论文库 HTTPS 地址。按 [首次配置](tacc/TACC.md#首次配置从新账号注册到网页研究)操作；本机可用 `./scripts/local-research configure` 和 `./scripts/research up`，没有固定公网入口时按 [隧道流程](tacc/TACC.md#本机一键启动)配置。
- **TACC 模型：** 按 [模型服务说明](model-server/README.md)启动 GPU 服务。网页模型管理仍提交原版 `server/`；使用 [优化版 `server-opt/`](model-server/server-opt/README.md) 时，手动提交 GPU 作业，并在新建研究中选择「指定服务地址」。Agent 作业必须能访问该地址；集群内网地址不保证能从 ECS 或个人电脑直接访问。模型服务和 Agent CPU 作业分别管理。
- **已部署 ECS：** 使用已安装的 systemd 服务、Nginx 和 HTTPS；在有权限的账号下执行 `./scripts/research up`。设置计算节点可达的 `AGENT_LIBRARY_PUBLIC_URL`，通过自动部署流程更新代码。本地开发脚本不会安装这些生产设施。

### 配置、数据与运行边界

- 配置样例分别位于 `backend/.env.example`、`agent/.env.example` 和 `frontend/.env.example`。API 和后端 Worker 共用数据库、存储及账号密钥；环境变量优先于 `.env`。`VITE_*` 会进入浏览器，只能放公开配置。
- 网页 arXiv 搜索/导入需开启 `ARXIV_ENABLED`、填写联系邮箱并运行 Import Worker；Agent 外部搜索另需 Tavily。Retrieval Extension 的 Embedding 和可选开关见 [Agent 文档](agent/README.md)。
- 后端任务详情接口提供 DeepSeek 五维评分、Agent 调用与 Token 统计、模型服务性能及缓存指标，字段和获取方式见 [任务指标契约](backend/README.md#任务指标与前端接入)。模型服务未返回的指标会标为不可用；GPU 为采样快照，不能当作任务平均利用率。
- 单份上传/导入 PDF 上限为 50 MB，最多预选 20 篇论文；公网反向代理还需预留 multipart 开销。步数、时限、输出 Token 和用户额度见 [派发与预算](backend/README.md#agent-dispatch)。全站研究并发数可在模型管理中设为 1–4，所有账号共用。
- PDF、数据库卷和日志不会随 Git 克隆迁移。Ctrl+C 停止本次启动的本地服务，数据库保留；停止数据库需从 `backend/` 执行 `docker compose stop postgres`。重新初始化或迁移前备份已有数据；修改 `.env` 不会重设已有数据库卷的账号密码。
- 示例验证小规模功能链路。真实论文的文本提取、上下文长度、模型输出和网络条件会影响回答及引用，扫描 PDF 可能缺少可用文本。TACC 运行时间还受排队及资源影响。模型和 SMTP 凭据需要使用者自行准备。

### Evaluation

项目实验由以下三部分组成。本节保留用例、数据、配置、执行命令和指标口径；具体性能数值放在对应报告与结果文件中。以下 Bash 命令在 Linux / macOS 或 Windows WSL 中运行，除注明外均从仓库根目录开始。

| 实验 | 研究问题 | 用例与配置 | 报告或产物 |
| --- | --- | --- | --- |
| [1. Agent 消融](#evaluation-agent) | RAG、Planner、Reflection 各自带来什么变化？ | 5 类用例 × 5 种组件配置，共 25 次运行。 | 每次的 `result.json`、内嵌 trace、执行日志；本次提供的消融报告未附冻结结果表。 |
| [2. Model Server](#evaluation-model-server) | 并发、调度预算与候选优化如何影响模型推理？ | 串行 / C=1 / C=4；prefill 预算 2048 / 4096 / 8192；GDN 与 N-gram 候选存档。 | [模型服务报告](model-server/server-opt/reports/Server_report.md)及[结果摘要](model-server/server-opt/results/)。 |
| [3. 全流程研究](#evaluation-end-to-end) | 用户研究任务的质量、开销和等待时间如何变化？ | 四类研究任务、15 对 Baseline / Extension，以及未配对运行存档。 | [全流程报告](docs/report.md)及[冻结清单](docs/evaluation/researcher-20261123.json)。 |

Agent 消融比较组件开关，Model Server 实验比较推理服务，全流程实验比较用户可见的完整研究链路；三者的模型来源、工作负载及计时边界不同，不能将其数据混为同一组对照。

<a id="evaluation-agent"></a>

#### 1. Agent 消融实验

##### 用例与组件配置

| 用例 | 数据和任务 | 论文库要求 |
| --- | --- | --- |
| `library-qa` | 查找 SkillOpt，解释其优化对象和保留一次更新的判断方法。 | 在自己的账号上传 / 导入 SkillOpt，确认按标题搜索可找到；记录论文版本、PDF SHA-256。 |
| `qa` | [`qa.json`](agent/examples/qa.json)：基于 *Attention Is All You Need* 解释 scaled dot-product attention 的 `sqrt(d_k)` 缩放。 | 无；预选 `1706.03762v7`。 |
| `summary` | [`summary.json`](agent/examples/summary.json)：总结同一篇论文的问题、方法、翻译结果及适用条件。 | 无；预选 `1706.03762v7`。 |
| `review` | [`review.json`](agent/examples/review.json)：查找 LoRA / QLoRA，比较方法与显存节约机制。 | 无；需要外部搜索。 |
| `discovery` | [`discovery.json`](agent/examples/discovery.json)：调研利用经验更新已有技能的 Agent 工作。 | 登录论文库，并保持各配置可见的库内容一致。 |

| 配置 | 运行入口 | RAG / `retrieve` | Planner | Reflection |
| --- | --- | --- | --- | --- |
| `baseline` | `baseline.py` | 关闭 | 关闭 | 关闭 |
| `rag` | `extension.py` | 开启 | 关闭 | 关闭 |
| `rag-planner` | `extension.py --planner` | 开启 | 开启 | 关闭 |
| `rag-reflection` | `extension.py --reflection` | 开启 | 关闭 | 开启 |
| `full` | `extension.py --planner --reflection` | 开启 | 开启 | 开启 |

这里的 `full` 是全部组件开启，独立于 `--context-policy full` 的完整历史策略。开启 RAG 表示提供 `retrieve` 工具，不保证模型一定调用；Reflection 在上下文压力收尾时可能不执行，需由 trace 核实实际路径。

##### 环境与 25 次运行命令

按 [Agent 文档](agent/README.md)初始化独立 Agent，在私有 `agent/.env` 配置百炼 `BAILIAN_API_KEY`、`MODEL_BASE_URL`、`MODEL_NAME=qwen3.8-27b`、`MODEL_PROVIDER=bailian` 和 `TAVILY_API_KEY`。Embedding 使用 `text-embedding-v4`、1024 维。论文库用例还需运行 Getting Started 中的后端，配置 `AGENT_LIBRARY_BASE_URL`、`AGENT_LIBRARY_ORIGIN`，并使用已验证账号登录。可在私有 `.env` 配置 `AGENT_LIBRARY_USERNAME` / `AGENT_LIBRARY_PASSWORD`，否则带 `--library-login` 的运行会交互询问。以下不使用 `--persist`，无需 Neon 数据库。

当前仓库有 4 份示例，`agent/run.sh` 只比较 Baseline / Extension。以下命令按报告中的任务描述补充 `library-qa`，显式运行五种配置；不修改 Agent 源码。固定主 Agent 步数 40、任务时限 600 秒、单次输出 4096 Token、上下文 32000、完整历史策略及 0.9 收尾阈值。它们是当前示例默认值的显式设置，与全流程实验的动态预算分开记录。

```bash
cd agent
uv sync --frozen
OUT="$PWD/runs/ablation/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT/tasks"
uv run --frozen python - "$OUT/tasks" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
cases = {path.stem: json.loads(path.read_text(encoding="utf-8"))
         for path in Path("examples").glob("*.json")}
cases["library-qa"] = {
    "question": "Find the SkillOpt paper in my library. Explain what SkillOpt optimizes and how it decides whether to keep an update. Cite the original PDF evidence.",
    "sources": [], "allow_search": True, "max_papers": 1,
}
for name, task in cases.items():
    task.update(max_steps=40, timeout_seconds=600, max_output_tokens=4096)
    (target / f"{name}.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
PY

status=0
for task in "$OUT/tasks/"*.json; do
  name=$(basename "$task" .json)
  login=()
  if [[ "$name" == library-qa || "$name" == discovery ]]; then login=(--library-login); fi
  for variant in baseline rag rag-planner rag-reflection full; do
    directory="$OUT/$name/$variant"
    mkdir -p "$directory"
    entry=extension.py
    flags=(--index-dir "$directory/index")
    case "$variant" in
      baseline) entry=baseline.py; flags=() ;;
      rag-planner) flags+=(--planner) ;;
      rag-reflection) flags+=(--reflection) ;;
      full) flags+=(--planner --reflection) ;;
    esac
    printf 'Running %s / %s\n' "$name" "$variant"
    if ! uv run --frozen python "$entry" --task "$task" \
        --context-window 32000 --context-policy full --context-finalize-ratio 0.9 \
        --output "$directory/result.json" "${flags[@]}" "${login[@]}" \
        > "$directory/run.log" 2>&1; then status=1; fi
  done
done
printf 'Batch: %s\nExit summary: %s (0 means all CLI runs succeeded)\n' "$OUT" "$status"
cd ..
```

每例每配置输出 `agent/runs/ablation/<batch>/<case>/<variant>/result.json` 和 `run.log`，trace 保存在 `result.json` 中，当前 CLI 不另写 `trace.json`。保留失败、`partial` 和缺失输出；CLI 返回成功也可能是 `partial`，需分别检查。RAG 索引按本轮用例 / 配置隔离，PDF 缓存仍由 Agent 共用；记录冷热缓存条件，重复实验使用新的批次目录。

##### 指标与复现边界

按相同用例比较 `usage.elapsed_seconds`、步数、模型 / 工具调用、输入 / 输出 / 总 Token、`stop_reason`、引用及 `unresolved`，并从 trace 核对 `retrieve`、Planner、Reflection 和 Embedding 的实际开销。`rag` 对 `baseline`、`rag-planner` / `rag-reflection` 对 `rag`、`full` 对其余配置分别回答不同的增量问题。独立 CLI 不会自动触发后端 DeepSeek 评分；这些产物不能直接当作全流程评分表。

提供的消融报告没有附带 25 次冻结产物，也未固定 SkillOpt 的 arXiv 版本 / PDF 哈希；因此以上是按报告设计补齐的可执行复现流程，不承诺还原未归档的历史数值。动态搜索、论文库内容、缓存与模型服务更新均可能影响结果。建议交替配置顺序、多轮重复，并保存任务 JSON、代码 SHA、模型配置和全部输出。

<a id="evaluation-model-server"></a>

#### 2. Model Server 实验

##### 环境、数据与对照组

使用 TACC 课程公共 vLLM 运行环境和 Qwen3.8-27B-AWQ-INT4，申请两张 RTX 3090、TP=2、BF16、8 CPU，GPU 作业时限 1 小时；CPU 测试作业独立提交。报告环境为 vLLM 0.26.0、PyTorch 2.11.0+cu128、Transformers 5.10.4、Triton 3.6.0。公共环境与模型权重由课程提供，不需要本机编译或下载。先完成 `tcloud init`，执行环境权限要求见 [Server 前置条件](model-server/server-opt/README.md#prerequisites)。

固定 `max_model_len=36864`、`max_num_seqs=4`、`gpu_memory_utilization=0.9`、前缀缓存开启、attention backend 为 `auto`。模型服务的 36864 是输入 / 输出合计上下文；下表测试客户端单独限制输入不超过 32767、输出最多 4096 Token，**不是将 Agent 或服务的输出上限改回 4096**。`max_num_batched_tokens` 是每轮调度预算，与输出上限不同。

| 数据 / 协议 | 测试请求 | 目的 |
| --- | --- | --- |
| [`serial-long-copy-boundary-v2`](model-server/server-opt/evaluation/data/serial-long-copy-boundary-v2.workload.json) | 4 轮 × 6 题，24 次正式请求。 | 长文引用、字段提取与完整记录复制的串行对照。 |
| `serial-long-copy-screen-v1`，由 [`quick_workload.py`](model-server/server-opt/evaluation/serial/quick_workload.py)选取子集 | 2 轮 × 4 题，8 次正式请求。 | 串行 prefill 预算快速筛选。 |
| [`concurrent-long-copy-screen-v1`](model-server/server-opt/evaluation/data/concurrent-long-copy-screen-v1.workload.json) | 2 波 × 4 请求，8 次正式请求。 | 固定工作负载下的 C=1 / C=4 与 C=4 预算比较。 |

三个协议均先执行 3 次不计入正式统计的预热。不得把 8 请求 screen 与 24 请求正式协议混合汇总。完整执行流程与报告对应关系如下：

| 对照 | 固定 / 变化项 | 复现说明与报告 |
| --- | --- | --- |
| 串行预算筛选 | 串行客户端，预算 2048 / 4096 / 8192。 | [步骤 A](model-server/server-opt/README.md#experiment-a-serial-e00-and-prefill-budget-experiment)，报告 §3.1。 |
| 并发对照 | 固定预算 4096，仅将客户端并发从 C=1 改为 C=4。 | [步骤 B](model-server/server-opt/README.md#experiment-b-concurrent-baseline)，报告 §3.2。 |
| C=4 调度预算 | 固定 C=4，预算 2048 / 4096 / 8192；每档新建服务。 | [步骤 C](model-server/server-opt/README.md#experiment-c-c4-chunked-prefill-experiment)，报告 §3.3。 |
| GDN indexed-state、GPU N-gram speculative decoding | 历史私有运行时候选，分别比较状态读写和投机解码。 | 报告 §3.4 / §3.5，[结果存档](model-server/server-opt/results/)与[复现范围限制](model-server/server-opt/README.md#known-limitations)；完整私有源码 / 构建树未包含，不能仅用公共包重跑候选。 |

##### 提交服务与独立测试客户端

以下示例先运行预算 4096、C=4。将预算依次改为 2048 和 8192，并为每档创建新的目录及服务 / 客户端作业，可完成调度预算比较。只修改工作副本，保留仓库中的最终配置：

```bash
BUDGET=4096
RUN_DIR="$PWD/runtime/evaluation/model-server/$(date -u +%Y%m%dT%H%M%SZ)-b$BUDGET"
mkdir -p "$(dirname "$RUN_DIR")"
test ! -e "$RUN_DIR"
cp -a model-server/server-opt "$RUN_DIR"
python3 - "$RUN_DIR" "$BUDGET" <<'PY'
import json
import sys
from pathlib import Path

root, budget = Path(sys.argv[1]), int(sys.argv[2])
for relative in ("service_config.json", "evaluation/serial/service_config.json", "evaluation/concurrency/service_config.json"):
    path = root / relative
    config = json.loads(path.read_text())
    config.update(max_num_batched_tokens=budget, profile=f"repro-b{budget}")
    path.write_text(json.dumps(config, indent=2) + "\n")
PY
cd "$RUN_DIR"
bash setup-sdk-account.sh
tcloud submit
```

记录返回的 GPU 作业号，替换下面占位值。查看服务日志，等 `Application startup complete.` 出现后，将本轮 `SERVICE_BASE_URL` 填入 `BASE_URL`；不要复用历史节点地址：

```bash
GPU_ID='<本轮 GPU 作业号>'
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-public-serve-agent-${GPU_ID}.log"
BASE_URL='http://<本轮节点>:8000/v1'
cd "$RUN_DIR/evaluation/concurrency"
printf '%s\n' "$GPU_ID" > service-job-id.txt
printf '%s\n' "$BASE_URL" > server-url.txt
printf '4\n' > concurrency-level.txt
tcloud submit
```

CPU 作业结束后再下载证据；将 `CLIENT_ID` 替换为本轮 CPU 作业号：

```bash
CLIENT_ID='<本轮 CPU 作业号>'
tcloud ps -j "$CLIENT_ID"
tcloud cat "slurm_log/qwen-concurrency-quality-${CLIENT_ID}.log"
RESULT="$RUN_DIR/results/job-$CLIENT_ID"
mkdir -p "$RESULT"
for name in summary.json answers.jsonl workload.json warmup.json tokenization.json \
            service_config.json server-metrics-before.txt server-metrics-after.txt metrics-boundaries.jsonl; do
  tcloud download "model-server-results/job-$CLIENT_ID/$name" "$RESULT/$name"
done
tcloud download "slurm_log/qwen-concurrency-quality-${CLIENT_ID}.log" "$RESULT/client.log"
tcloud download "slurm_log/qwen-public-serve-agent-${GPU_ID}.log" "$RESULT/service.log"
```

并发对照须在预算 **4096** 的同一服务上再运行 C=1：将 `concurrency-level.txt` 写为 `1`，重新 `tcloud submit`，记录新的 CPU ID 并单独保存结果。串行测试则进入 `$RUN_DIR/evaluation/serial`，同样填写 `service-job-id.txt`、`server-url.txt`，将 `measurement-mode.txt` 写为 `quick`（8 请求）或 `long`（24 请求），再提交；日志名为 `qwen-latency-quality-<CPU_ID>.log`。各运行完成并保存证据后，执行 `tcloud cancel -j "$GPU_ID"` 释放自己提交的服务，最后用 `cd /path/to/project` 返回仓库根目录。

##### 核验、指标与局限

检查实际协议、正式请求数、quality gate、无输出截断、`workload_sha256`、服务参数和测量代码版本。并发日志应含 `PROTOCOL=concurrent-long-copy-screen-v1`、`WARMUP_COMPLETE=3`、`RUN_COMPLETE measured_requests=8 PROFILE=concurrency`。比较 `summary.json` 中的 TTFT、TPOT、端到端延迟、requests/s、输出 tokens/s、Token 用量、缓存命中 / 查询、prefill、排队及抢占，并关联 [Server report §3](model-server/server-opt/reports/Server_report.md#3-experimental-results)和[冻结结果](model-server/server-opt/results/)。

模型基准客户端使用流式请求计时，`/metrics` 在实验边界采集；全流程 Agent 使用非流式请求及服务端原生遥测，两类 TTFT 不应直接混算。历史基准 sidecar 采样文件为空，GPU 利用率、显存及 KV-cache 峰值应记为不可用。小样本、节点差异、共享负载、缓存和首次 JIT 都可能造成变化；该基准不等同于真实 Agent 任务吞吐量。8192 是该模型实验选择的吞吐导向配置，网页模型管理仍默认部署 `server/`，不会因本节复现而自动改用 `server-opt/`。

<a id="evaluation-end-to-end"></a>

#### 3. 全流程研究实验

本实验比较 **Agent Baseline 与 Extension** 在论文库、TCloud 派发、模型服务、引用和独立评分组成的链路中的表现；实测结果与对比分析见 [全流程报告](docs/report.md)。它不等同于上述五配置消融，也不默认包含模型服务优化。

**在线查看已有实验结果：** 打开 [https://8.218.149.237/](https://8.218.149.237/)，使用用户名 `Researcher`（区分大小写）、密码 `123456` 登录。进入研究记录，打开对应任务详情，即可查看研究答案、引用、评分和性能指标。

##### 1. 测试用例与论文数据

[实验清单](docs/evaluation/researcher-20261123.json)保存 `Researcher` 账号实验的原始问题、各模式的论文顺序、PDF SHA-256、预算和历史任务/评分 ID。请使用自己的验证账号重跑，无需该账号的密码或数据库副本。清单中的 `cases` 是配对用例，`runs` 是脱敏后的历史指标快照。

| 类型 | 用例 ID | 问题范围 | 初始论文 |
| --- | --- | --- | --- |
| 单论文问答 | `QA01`–`QA03` | FlashAttention-2 计算复杂度、Longformer 局部/全局注意力、Performer 近似性质 | 每例 1 篇 |
| 单论文摘要 | `SUM01`–`SUM03` | Transformer 架构与实验、Transformer 翻译结果与局限、FlashAttention 方法与证据 | 每例 1 篇；前两例使用同一份 Transformer PDF |
| 多论文综述 | `REV01`–`REV04` | 三篇线性注意力、五篇高效注意力、两种详细程度的 FlashAttention 对比 | 分别为 3、5、2、2 篇 |
| 领域调研 | `SUR01`–`SUR05` | LoRA/QLoRA、自演化 Agent 技能、稀疏注意力、幻觉检测与缓解、RAG | 不预选论文，由 Agent 检索 |

每例运行 Baseline 和 Extension 各一次，共 30 个研究任务。清单另保留 6 个无 Baseline 配对的 Extension 历史运行，作为审计记录，不加入配对比较。

从 arXiv 下载以下**指定版本**的 PDF，上传至自己的论文库并等待全部变为 `ready`；也可按 [导入接口](docs/api-contract.md)逐篇导入。完整标题、页数和哈希见清单的 `papers`。

| 论文 | arXiv 版本 |
| --- | --- |
| Attention Is All You Need | `1706.03762v7` |
| Big Bird | `2007.14062v2` |
| FlashAttention-2 | `2307.08691v1` |
| FlashAttention | `2205.14135v2` |
| Linformer | `2006.04768v3` |
| Longformer | `2004.05150v2` |
| Rethinking Attention with Performers | `2009.14794v4` |
| Transformers are RNNs | `2006.16236v3` |

通过 `GET /api/v1/papers?limit=50&offset=0` 分页核对 `sha256`，不要复用历史账号的论文 UUID。下方命令会按哈希映射当前账号的 UUID；若版本相同但字节不同，也应记录为数据变化。领域调研的搜索结果会随时间变化，原始搜索结果和全部外部 PDF 未打包，因此不能保证重现相同的检索语料。

##### 2. 运行环境与配置

完成 Getting Started 中的账号、论文库、TCloud、Tavily 和评分 Worker 配置。按 [模型服务说明](model-server/README.md)启动课程 Qwen 服务，等模型管理页显示就绪，并在同一对任务的两次运行期间保持同一服务。历史实验使用 `qwen3.8-27b`，温度为 `0`，由 TACC CPU Agent 作业访问 GPU 模型服务；ECS 无需直接访问 GPU 节点的内网地址。记录本次 `git rev-parse HEAD`、GPU 作业号、模型版本及服务启动配置；历史任务未保存完整的模型服务启动参数，不能据此认定使用了优化版服务。

在私有 `backend/.env` 设置以下实验参数，然后重启 API、Agent Runner 和评分 Worker；沿用启动器时重新执行对应系统的 `start`，ECS 的服务管理方式见 [服务启动说明](docs/service_launch.md)。

```dotenv
TASK_RUNNER=agent
AGENT_DISPATCH_ENABLED=true
AGENT_TRANSPORT=tcloud
AGENT_SEARCH_MAX_PAPERS=5
AGENT_MAX_STEPS=200
AGENT_TIMEOUT_SECONDS=1800
AGENT_OUTPUT_TOKENS=16384
AGENT_CONTEXT_TOKENS=32000
AGENT_PERSIST=false
EVALUATION_ENABLED=true
EVALUATION_BASE_URL=https://api.deepseek.com
EVALUATION_MODEL=deepseek-flash
EVALUATION_TIMEOUT_SECONDS=180
EVALUATION_MAX_INPUT_BYTES=256000
EVALUATION_DAILY_LIMIT=50
```

`EVALUATION_API_KEY`、`TAVILY_API_KEY` 和 TCloud/论文库连接参数按 Getting Started 私下配置。Extension 还需可用的百炼 Embedding 凭据，模型为 `text-embedding-v4`、1024 维，配置方式见 [Agent 文档](agent/README.md)及 [TACC 配置](tacc/TACC.md)。`AGENT_TCLOUD_MODEL_ENV_FILE` 应指向包含这些凭据的私有文件；请勿将密钥写入实验清单或结果。

必须把 `AGENT_SEARCH_MAX_PAPERS` 设为 **5**，而不是直接沿用配置样例中的值。其余步数和时限为全局上限，实际预算由初始论文数与追加检索额度计算：

| 初始论文数 | 最多研究论文数 | Agent 步数上限 | 任务时限（秒） |
| --- | --- | --- | --- |
| 0 | 5 | 72 | 600 |
| 1 | 6 | 80 | 660 |
| 2 | 7 | 88 | 720 |
| 3 | 8 | 96 | 780 |
| 5 | 10 | 112 | 900 |

两种模式均启用追加检索、使用 `context_policy: "compact"`、`context_finalize_ratio: 0.9`，单次最大输出为 16384 Token。Baseline 的 `planner` / `reflection` 为 `false`，Extension 为 `true`。清单保存每次请求的配置，以下命令直接使用它们；功能是否实际执行仍需检查 trace。

##### 3. 提交、等待与保存

以下命令在**已登录网页的 Chrome / Edge 开发者工具 Console** 中执行，使用当前会话及 CSRF Token，无需在命令中填写账号密码。运行后选择本地仓库的 `docs/evaluation/researcher-20261123.json`。默认只重跑 `QA01` 的一对任务；确认链路后，修改 `caseIds` 分批覆盖全部用例，例如 `["SUM01", "SUM02", "SUM03"]`。仅在模型服务剩余时限足够时设为 `null`，顺序运行全部 15 对；否则在批次之间续开 GPU 服务并记录新的服务信息，避免跨服务配对。重跑会消耗模型、搜索、集群资源和用户额度；默认单用户每日研究/新评分版本额度均为 50，已用额度也计入。

```javascript
(async () => {
  const caseIds = ["QA01"];
  const fixture = await new Promise((resolve, reject) => {
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = ".json";
    picker.onchange = async () => {
      try { resolve(JSON.parse(await picker.files[0].text())); }
      catch (error) { reject(error); }
    };
    picker.oncancel = () => reject(new Error("No fixture selected"));
    picker.click();
  });
  const api = async (path, options = {}) => {
    const response = await fetch(`/api/v1/${path}`, {
      credentials: "same-origin", ...options
    });
    if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
    return response.json();
  };
  const {csrf_token} = await api("auth/me");
  const papersByHash = new Map();
  for (let offset = 0; ; offset += 50) {
    const page = await api(`papers?limit=50&offset=${offset}`);
    for (const paper of page.items) {
      if (paper.status === "ready") papersByHash.set(paper.sha256, paper.id);
    }
    if (offset + page.items.length >= page.total) break;
  }
  const cases = fixture.cases.filter(item => caseIds === null || caseIds.includes(item.id));
  if (!cases.length || (caseIds !== null && cases.length !== caseIds.length)) {
    throw new Error("Check caseIds against the fixture");
  }
  for (const item of cases) for (const variant of Object.values(item.variants)) {
    for (const hash of variant.paper_sha256s) {
      if (!papersByHash.has(hash)) throw new Error(`Missing ready PDF: ${hash}`);
    }
  }
  window.evaluationRuns ??= [];
  for (const item of cases) for (const workflow of ["baseline", "extension"]) {
    const variant = item.variants[workflow];
    const accepted = await api("agent-research", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf_token},
      body: JSON.stringify({question: item.question, allow_search: true,
        paper_ids: variant.paper_sha256s.map(hash => papersByHash.get(hash)),
        research: variant.research})
    });
    const saved = {case_id: item.id, workflow, task_id: accepted.task_id};
    window.evaluationRuns.push(saved);
    const deadline = Date.now() + 60 * 60 * 1000;
    while (true) {
      saved.record = await api(`agent-research/${saved.task_id}`);
      saved.task = await api(`tasks/${saved.task_id}`);
      const researchDone = ["succeeded", "failed"].includes(saved.record.status);
      const judge = saved.record.metrics.evaluation;
      if (researchDone && !["pending", "running"].includes(judge.status)) break;
      if (Date.now() > deadline) throw new Error(`Wait expired; keep task ${saved.task_id}`);
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
    console.log(item.id, workflow, saved.task_id, saved.record.status,
      saved.record.result?.stop_reason, saved.record.metrics.evaluation.status);
  }
  copy(JSON.stringify(window.evaluationRuns, null, 2));
  console.log("Copied results. Save under runtime/evaluation/; do not commit private answers.");
})();
```

将剪贴板结果保存到 `runtime/evaluation/rerun.json`。脚本保留失败任务，遇到 HTTP 错误或等待超时会停止后续提交，已提交 ID 保留在 `window.evaluationRuns`；可随时执行 `copy(JSON.stringify(window.evaluationRuns, null, 2))` 保存现场。网页刷新会清除该变量，因此长实验期间保持页面打开。等待超时不会取消远程作业，继续前先按任务 ID 查询状态，避免重复创建。

也可在网页逐例创建研究：复制清单中的原始 `question`，按对应模式的 `paper_sha256s` 顺序选论文，设置上述模式开关后提交。每例先完成一侧再提交另一侧，保存两次任务 ID；全量比较需覆盖所有用例，不能只保留高分或成功样本。若要评估并发性能，应另设固定并发实验，不能与这里的串行结果合并。

##### 4. 采集与核算指标

| 数据 | 获取方式与口径 |
| --- | --- |
| DeepSeek 五维评分 | `GET /api/v1/tasks/{id}/evaluation`，以及任务详情的 `metrics.evaluation`；保存 `evaluation_id`、`prompt_version`、`rubric_version`、`assessment`。各维 0–5 分，权重依次为事实与证据一致性 30、引用支持 30、完成度 20、分析质量 15、清晰度 5，总分 `Σ(维度分 × 权重 / 5)`。 |
| Agent 步数、调用与 Token | `GET /api/v1/agent-research/{id}` 的 `metrics.agent`；Agent 自身耗时取 `result.usage.elapsed_seconds`。聊天 Token 不含独立评分和另行记录的 Embedding 消耗。 |
| 平台端到端耗时 | `GET /api/v1/tasks/{id}` 的 `stats.end_to_end_ms / 1000`；包括派发、排队和回传，不包含后续独立评分。不要与 Agent 自身耗时混用。 |
| TTFT、TPOT / mean ITL、tokens/sec | 任务详情的 `metrics.model_server`。原生来源分别为 `metrics.time_to_first_token_ms`、`metrics.mean_itl_ms`、`metrics.tokens_per_second`；组内比较取各任务有效请求均值的算术平均，并报告样本数、来源及缺失情况。 |
| 缓存命中/查询 Token 与命中率 | `metrics.model_server.cache_hit_tokens`、`cache_query_tokens`、`cache_hit_ratio`；组级命中率使用 `Σ命中 Token / Σ查询 Token`，检查 `cache_usage_complete`，不要直接平均百分比。 |
| GPU 利用率 | `metrics.model_server.gpus` 是已分配设备的完成时采样快照，保存设备 UUID 和采样时间；不是本任务的平均/峰值利用率。 |

各类型内按同一问题与 PDF 哈希集合配对，分别汇总 Baseline / Extension，并注明样本数和 `Extension − Baseline` 的方向。论文顺序另行记录；历史清单保留了实际顺序，不自动排序。任务 `status` 与 Agent `stop_reason` 分别检查，`succeeded` 不代表研究内容完整；评分失败、`insufficient_evidence` 或指标缺失均不得补零。

模型服务负载、缓存、TACC 排队、动态搜索、PDF 获取及模型/评分服务更新都会影响重跑结果，即使温度为 0 也不保证逐字或数值一致。建议新增多轮配对重复，交替运行顺序并报告分布；不要将单轮结果解释为确定的因果提升。报告中的具体数值及适用范围见 [实验报告](docs/report.md)；独立模型服务实验另见 [Server report](model-server/server-opt/reports/Server_report.md)。
