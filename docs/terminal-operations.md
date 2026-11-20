# 本地启动、测试与验收操作手册

适用环境：Windows PowerShell、macOS Terminal（zsh/bash）、当前仓库。更新日期：2026-11-19。第 0 节提供两种系统从新建数据库到完整启动的命令及预期结果；第 1 节起保留原有 Windows 日常操作、测试和验收说明。

**首次安装或需要一套全新的数据库，从第 0 节按顺序执行。** 第 2.1 节是此前本机验收库的历史配置，新环境不要照搬该项目名。本文只提供操作者执行的步骤，不表示这些命令已经在你的机器上运行。

**每个命令块都从项目根目录开始执行**（包含 README.md、backend、frontend、docs 的目录）。在 VS Code 中打开项目根文件夹后，新建终端并确认当前目录。命令块执行后可能停留在 backend 或 frontend；复用该终端执行下一个命令块前，先运行 `Set-Location ..` 返回根目录。运行中的服务终端保持不动，检查命令使用另一个终端。

## 0. 从零启动：Windows / macOS

### 0.1 执行约定与准备条件

以下流程适用于本地开发，不是公网生产部署。需要提前安装 Git、Docker Desktop、uv、Python 3.11+ 和 Node.js/npm。Node.js 版本须满足仓库 package.json 的要求：20.x 至少 20.19.0，或 22.12.0 及以上。工具尚未安装时，先完成对应系统的安装并重新打开终端，再继续本节；下面的依赖安装命令负责安装项目依赖。

- 已有项目代码时，在 VS Code 中打开仓库根文件夹。尚未获取代码时，先用 Git 克隆自己要运行的仓库和分支，再打开该文件夹；不需要为了启动自动切换分支。
- Windows 使用 PowerShell，macOS 使用 Terminal 的 zsh/bash。只复制对应系统的命令，不要把 PowerShell 的反引号续行或 `$env:` 写法复制到 macOS。
- **本节每个可执行命令块都从项目根目录开始，并在有限命令执行完后返回根目录。** 服务启动命令会持续占用终端；每个服务另开一个终端，并确认新终端也位于项目根目录。
- 本节统一新建 Compose 项目 `acs-local`，宿主机数据库端口 `55433`，数据库和用户均为 `literature_dev`。容器内部端口仍是 `5432`，与 API 8000、前端 5173 不同。
- 初次执行会创建 `acs-local` 对应的数据卷；再次使用相同项目名会复用该数据卷，不会自动清空数据库。若本机已经有这套项目，需要另一套空数据库，应换用新的 Compose 项目名，并在已有容器同时运行时分配不同的宿主机端口，后续所有命令保持一致。
- 如果原有 API、Worker 或前端仍在运行，先在对应终端按 `Ctrl+C` 停止，再修改配置。新数据库使用独立存储目录 `backend/runtime/storage-local`，旧数据库及旧文件不需要删除。
- 不需要在宿主机另外安装 PostgreSQL，也不需要单独启动 `agent/` 服务；当前真实研究任务由后端 Runner Worker 执行。

全文的数据库密码示例仅供本机开发。模型密钥、QQ SMTP 授权码、账号密钥及 `.env` 只保存在本机，不要发到聊天、截图或提交 Git。

### 0.2 检查工具和 Docker 引擎

先打开 Docker Desktop，等待引擎就绪。

**Windows PowerShell，项目根目录：**

~~~powershell
Test-Path .\backend\compose.yaml
git --version
docker version
docker compose version
uv --version
node --version
npm.cmd --version
~~~

**macOS Terminal，项目根目录：**

~~~bash
test -f ./backend/compose.yaml && echo "project root: OK"
git --version
docker version
docker compose version
uv --version
node --version
npm --version
~~~

预期结果：

- Windows 第一条为 `True`；macOS 第一条打印 `project root: OK`。没有输出或返回 False 时，先回到正确的项目根目录。
- Docker 同时显示 Client 和 Server，且没有无法连接 daemon 的错误；本项目的 postgres 镜像需要 Linux 容器环境。
- 其他命令正常显示版本，Node.js 满足第 0.1 节要求。某条命令失败就先处理该工具，不要继续后续步骤。

### 0.3 安装项目依赖并准备配置文件

只在配置文件不存在时复制模板，避免覆盖已有密钥。

**Windows PowerShell，项目根目录：**

~~~powershell
Set-Location .\backend
uv sync --locked
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Set-Location ..\frontend
npm.cmd ci
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Set-Location ..
~~~

**macOS Terminal，项目根目录：**

~~~bash
cd ./backend
uv sync --locked
if [ ! -e .env ]; then cp .env.example .env; fi
cd ../frontend
npm ci
if [ ! -e .env ]; then cp .env.example .env; fi
cd ..
~~~

预期结果：两次依赖安装均成功退出；存在 `backend/.venv`、`frontend/node_modules`、`backend/.env`、`frontend/.env`。无需手动激活 Python 虚拟环境，后续 `uv run --locked` 会使用项目环境。初次安装可能下载 Python 或依赖；锁文件不匹配时先确认代码和锁文件完整，不要直接删除锁文件绕过错误。命令块中的某条安装命令报错时，停止并解决后再继续，不要仅凭最后一条目录切换成功判断安装成功。

### 0.4 编辑持久化配置

用编辑器打开 `backend/.env`，**逐项修改已有配置，不要重复追加同名变量**。除下面列出的变量外，保留 `.env.example` 中的其他默认配置。

以下是需要填入文件的内容，不是终端命令：

~~~dotenv
# 全新本地数据库；这五个值必须相互匹配
POSTGRES_DB=literature_dev
POSTGRES_USER=literature_dev
POSTGRES_PASSWORD=local-development-only
POSTGRES_PORT=55433
DATABASE_URL=postgresql+psycopg://literature_dev:local-development-only@127.0.0.1:55433/literature_dev
STORAGE_ROOT=runtime/storage-local

# 真实模型任务，沿用此前项目选择的 DeepSeek 配置
TASK_RUNNER=langgraph
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_ID=deepseek-flash
LLM_API_KEY=替换为你自己的模型API密钥
LLM_THINKING_MODE=disabled

# 本机前端与登录 Cookie
FRONTEND_PUBLIC_URL=http://127.0.0.1:5173
AUTH_COOKIE_SECURE=false
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
AUTH_RATE_KEY=
AUTH_CSRF_KEY=

# QQ 邮箱发信；注册用户可以使用其他邮箱收信
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USERNAME=替换为完整QQ邮箱地址
SMTP_FROM=替换为与SMTP_USERNAME相同的邮箱地址
SMTP_AUTH_CODE=替换为QQ邮箱SMTP授权码
MAIL_OUTBOX_KEY=

# 真实 arXiv 搜索与导入
ARXIV_ENABLED=true
ARXIV_CONTACT_EMAIL=替换为你的真实联系邮箱
~~~

注意：

- 数据库密码可自行更换，但 `POSTGRES_PASSWORD` 与 `DATABASE_URL` 内的密码必须相同。URL 中包含 `@`、`:`、`/`、`#` 等特殊字符的密码需要 URL 编码；本地首次配置可使用不含这些字符的密码，避免连接串解析错误。
- Compose 的 POSTGRES_* 只负责初始化新数据卷。已经初始化的数据卷不会因为改 `.env` 自动修改数据库名、用户或密码；发生认证错误时先核对旧卷和项目名，不要删除数据解决。
- `deepseek-flash` 是本项目此前使用的模型 ID 示例，不是对服务商当前可用模型的保证。如果你的账号使用其他 ID，以实际可用配置为准。不要把旧的代理地址和新服务商密钥混用。
- QQ 发信使用 SMTP 授权码，不是邮箱登录密码；需先在 QQ 邮箱中启用相应服务并取得授权码。`SMTP_USERNAME` 与 `SMTP_FROM` 必须是同一个完整邮箱地址。
- `AUTH_RATE_KEY`、`AUTH_CSRF_KEY`、`MAIL_OUTBOX_KEY` 在下一节生成。若原文件已有有效且不同的密钥，可继续保留，不必重新生成。
- 暂时不测试 arXiv 时，设 `ARXIV_ENABLED=false`，同时将 `ARXIV_CONTACT_EMAIL=` 留空（或保留有效的真实联系邮箱），并跳过 Import Worker；本地 PDF 上传、解析及研究仍可使用。即使关闭 arXiv，配置加载仍会校验非空联系邮箱，不能保留示例占位文本。
- 任务预算由后端动态管理。首次启动不需要自行计算或逐个终端设置 Token、步骤或超时预算，保留模板中的 RESEARCH_*、REVIEW_* 默认值即可。

`frontend/.env` 保持以下配置；模型和邮箱密钥不能放到任何 VITE_* 变量中：

~~~dotenv
VITE_API_BASE_URL=
API_PROXY_TARGET=http://127.0.0.1:8000
~~~

浏览器统一使用 `127.0.0.1`，不要中途切到 `localhost`，否则可能影响可信 Origin 和账号会话。

### 0.5 首次生成账号及邮件密钥

仅在这三个变量尚未配置时执行。命令把三个独立随机值复制到本机剪贴板，不会把密钥打印到终端。

**Windows PowerShell，项目根目录：**

~~~powershell
Set-Location .\backend
uv run --locked python -c "import secrets; from cryptography.fernet import Fernet; print('AUTH_RATE_KEY='+secrets.token_urlsafe(32)); print('AUTH_CSRF_KEY='+secrets.token_urlsafe(32)); print('MAIL_OUTBOX_KEY='+Fernet.generate_key().decode())" | Set-Clipboard
Set-Location ..
~~~

**macOS Terminal，项目根目录：**

~~~bash
cd ./backend
uv run --locked python -c "import secrets; from cryptography.fernet import Fernet; print('AUTH_RATE_KEY='+secrets.token_urlsafe(32)); print('AUTH_CSRF_KEY='+secrets.token_urlsafe(32)); print('MAIL_OUTBOX_KEY='+Fernet.generate_key().decode())" | pbcopy
cd ..
~~~

预期结果：命令退出，终端不显示密钥；在 `backend/.env` 中粘贴剪贴板内容，替换对应的三行空值并保存。三个值必须保留在同一个 `.env` 中供所有后端进程共用。不要每次启动重新生成，特别是邮件队列中还有加密消息时。粘贴完成后可复制一段普通文本覆盖剪贴板；若使用剪贴板历史或云同步，按自己的本机设置清理敏感记录。

### 0.6 检查实际生效配置

进程环境变量优先于 `.env`。如果此前设置过系统或终端级的 DATABASE_URL、POSTGRES_*、TASK_RUNNER、LLM_* 等变量，先按第 0.12 节处理覆盖，再启动服务。下面只读取配置和校验密钥格式，不访问模型、arXiv、邮箱或数据库，也不输出密钥。

**Windows PowerShell，项目根目录：**

~~~powershell
Set-Location .\backend
uv run --locked python -c "from app.config import Settings; from app.auth.security import check_config; from sqlalchemy.engine import make_url; s=Settings(); check_config(s, mail=True); u=make_url(s.database_url.get_secret_value()); print('Database:', u.host, u.port, u.database); print('Runner:', s.task_runner); print('Base URL:', s.llm_base_url); print('Model:', s.llm_model_id); print('Thinking mode:', s.llm_thinking_mode); print('Real runner configured:', s.real_runner_configured); print('arXiv configured:', s.arxiv_configured); print('Auth/SMTP format: OK'); print('Frontend:', s.frontend_public_url); print('Storage:', s.storage_root)"
Set-Location ..
~~~

**macOS Terminal，项目根目录：**

~~~bash
cd ./backend
uv run --locked python -c "from app.config import Settings; from app.auth.security import check_config; from sqlalchemy.engine import make_url; s=Settings(); check_config(s, mail=True); u=make_url(s.database_url.get_secret_value()); print('Database:', u.host, u.port, u.database); print('Runner:', s.task_runner); print('Base URL:', s.llm_base_url); print('Model:', s.llm_model_id); print('Thinking mode:', s.llm_thinking_mode); print('Real runner configured:', s.real_runner_configured); print('arXiv configured:', s.arxiv_configured); print('Auth/SMTP format: OK'); print('Frontend:', s.frontend_public_url); print('Storage:', s.storage_root)"
cd ..
~~~

完整功能模式的预期输出包含：

~~~text
Database: 127.0.0.1 55433 literature_dev
Runner: langgraph
Base URL: https://api.deepseek.com
Model: deepseek-flash
Thinking mode: disabled
Real runner configured: True
arXiv configured: True
Auth/SMTP format: OK
Frontend: http://127.0.0.1:5173
Storage: <当前仓库>/backend/runtime/storage-local
~~~

若有意关闭 arXiv，其值为 False 是正常的。模型配置完整、账号及 SMTP 格式正确，并不表示外部服务连通或邮件一定能送达；后面的浏览器验收才会实际验证。

### 0.7 新建并启动 PostgreSQL 数据库

数据库和用户由 Compose 在新数据卷首次启动时自动创建，不需要先执行 CREATE DATABASE。这里固定写出 `acs-local`，不依赖其他终端中的临时变量。

**Windows PowerShell，项目根目录：**

~~~powershell
Set-Location .\backend
docker compose -p acs-local up -d --wait postgres
docker compose -p acs-local ps
docker compose -p acs-local exec -T postgres psql -U literature_dev -d literature_dev -c "SELECT current_database(), current_user, current_setting('server_version') AS postgres_version;"
Set-Location ..
~~~

**macOS Terminal，项目根目录：**

~~~bash
cd ./backend
docker compose -p acs-local up -d --wait postgres
docker compose -p acs-local ps
docker compose -p acs-local exec -T postgres psql -U literature_dev -d literature_dev -c "SELECT current_database(), current_user, current_setting('server_version') AS postgres_version;"
cd ..
~~~

预期结果：

- 首次运行创建 `acs-local` 的网络、数据库卷和 postgres 容器；首次拉取 postgres:17 镜像可能需要较长时间。
- `ps` 中 postgres 为 `Up ... (healthy)`，端口为 `127.0.0.1:55433->5432/tcp`。
- SQL 返回一行，数据库和用户均为 `literature_dev`，版本为 `17.x`；补丁版本不要求固定。
- `-d` 让数据库在后台运行，这个终端可以继续使用。后续一直使用相同 Compose 项目名和端口。

### 0.8 创建全部数据库表并检查迁移

此时数据库服务已启动，但应用表仍需 Alembic 创建。首次迁移前不要先启动 API 或任何 Worker。

**Windows PowerShell，项目根目录：**

~~~powershell
Set-Location .\backend
uv run --locked alembic heads
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
docker compose -p acs-local exec -T postgres psql -U literature_dev -d literature_dev -c "\dt"
Set-Location ..
~~~

**macOS Terminal，项目根目录：**

~~~bash
cd ./backend
uv run --locked alembic heads
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
docker compose -p acs-local exec -T postgres psql -U literature_dev -d literature_dev -c "\dt"
cd ..
~~~

预期结果：

- `upgrade head` 首次从初始迁移逐条升级，不能出现 traceback。
- 截至本文更新时，`heads` 和 `current` 均为 `20261115_0005 (head)`。如果后续代码新增迁移，以当前检出的 `alembic heads` 为准，`current` 应与之对应。
- `check` 输出 `No new upgrade operations detected.`。
- `\dt` 能看到 `alembic_version`、论文、任务、账号、邮件等应用表，不是空表列表。不要按早期版本的表数量判断当前迁移是否成功。

若账号迁移提示旧业务数据阻止升级，说明目标不是预期的空库；先核对第 0.6 节输出和 Compose 项目。不要为了完成首次启动去运行清库工具。

### 0.9 启动六个常驻终端

在 VS Code 中新建六个终端，可分别命名为 API、Parser、Runner、Import、Mail、Frontend。**每个终端都从项目根目录执行自己的命令块；不要在被服务占用的终端继续输入下一项。** Worker 空闲时可能没有持续日志，命令不退出且没有报错只是进程初步启动，仍需第 0.10 节验收实际处理。

#### 终端 1：API

Windows：

~~~powershell
Set-Location .\backend
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
~~~

macOS：

~~~bash
cd ./backend
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
~~~

预期：出现 `Uvicorn running on http://127.0.0.1:8000`、应用启动完成日志，终端持续运行。`--reload` 只用于本地开发，不会帮其他 Worker 自动重新加载配置。

#### 终端 2：PDF Parser Worker

Windows：

~~~powershell
Set-Location .\backend
uv run --locked python -m app.parser_worker
~~~

macOS：

~~~bash
cd ./backend
uv run --locked python -m app.parser_worker
~~~

预期：进程保持运行，无初始化错误；上传或导入文本 PDF 后，论文最终由 `uploaded` 进入 `ready`，可查看页数。未启动时，上传成功不代表解析已完成。扫描件 OCR 不在当前解析能力内。

#### 终端 3：真实研究 Runner Worker

Windows：

~~~powershell
Set-Location .\backend
uv run --locked python -m app.runner_worker
~~~

macOS：

~~~bash
cd ./backend
uv run --locked python -m app.runner_worker
~~~

预期：进程保持运行；创建新的真实摘要、问答或综述后，任务从排队进入执行。它会调用 `.env` 中配置的模型，可能产生费用；成功和结果质量必须实际创建任务验证。不要用 Mock Worker 替代后期待它处理真实任务。

#### 终端 4：arXiv Import Worker

Windows：

~~~powershell
Set-Location .\backend
uv run --locked python -m app.import_worker
~~~

macOS：

~~~bash
cd ./backend
uv run --locked python -m app.import_worker
~~~

预期：启用 arXiv 且联系邮箱有效时进程保持运行，能够处理导入队列。一次完整导入应先变为 `succeeded`，之后由 Parser 将论文变为 `ready`。只有搜索、不下载 PDF 时不依赖此进程；关闭 arXiv 时跳过此终端。

#### 终端 5：Mail Worker

Windows：

~~~powershell
Set-Location .\backend
uv run --locked python -m app.mail_worker
~~~

macOS：

~~~bash
cd ./backend
uv run --locked python -m app.mail_worker
~~~

预期：进程保持运行；通过前端注册或申请重置密码后，能在自己控制的收件邮箱收到邮件。API 只将邮件加入队列，不启动此 Worker 就不会完成投递。此进程可能真实发送邮件，不是无副作用的测试。

#### 终端 6：前端

Windows：

~~~powershell
Set-Location .\frontend
npm.cmd run dev
~~~

macOS：

~~~bash
cd ./frontend
npm run dev
~~~

预期：Vite 输出可访问的 `http://127.0.0.1:5173`，浏览器打开后显示账号页面。端口固定为 5173，若被占用会报错，不会自动换端口。前端通过同源 `/api`、`/health`、`/ready` 代理到 8000，无需把 API 密钥交给浏览器。

### 0.10 确认从基础启动到功能可用

先另开一个临时终端执行检查，不要关闭上述六个服务。

**Windows PowerShell，项目根目录：**

~~~powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 10 | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/ready' -TimeoutSec 10 | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://127.0.0.1:5173/ready' -TimeoutSec 10 | ConvertTo-Json -Compress
~~~

**macOS Terminal，项目根目录：**

~~~bash
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/health
printf '\n'
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/ready
printf '\n'
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:5173/ready
printf '\n'
~~~

预期按顺序为：

~~~json
{"status":"ok"}
{"status":"ready"}
{"status":"ready"}
~~~

第一项证明 API 存活，第二项检查数据库连接和迁移版本，第三项还检查 Vite 代理。**三项通过不表示 Worker、模型、邮件或 arXiv 已经验收通过。** 继续在浏览器按下表验证，全部成功才算对应功能启动完成。

| 顺序 | 你需要操作的功能 | 预期结果 | 失败先看哪里 |
| --- | --- | --- | --- |
| 1 | 打开 http://127.0.0.1:5173，注册自己的账号 | 收到验证邮件，验证后可登录；新库没有旧账号，需要重新注册 | API、Mail、SMTP 配置、收件箱和垃圾邮件 |
| 2 | 上传一份含可提取文字的 PDF | 论文变为 ready，页数正常，页内 PDF 可阅读 | API、Parser、共同数据库和存储目录 |
| 3 | 为这篇论文创建一个新的摘要任务 | 排队后进入执行，完成后显示摘要和引用，刷新仍可恢复 | Runner、模型地址/ID/密钥、任务错误信息 |
| 4 | 新建一个论文有直接依据的问答 | 显示回答，引用原文及 PDF 页码可核对 | Runner、检索与证据覆盖；无依据时允许证据不足 |
| 5 | 搜索 arXiv，并导入一篇论文 | 有搜索结果，导入 succeeded 后论文 ready，来源信息正常 | API 中的 arXiv 请求、Import、Parser；搜索失败不等于数据库故障 |
| 6 | 选择至少两篇 ready 论文，创建跨论文综述 | 显示综述、比较结果及引用；预算由后端处理 | Runner、任务记录和具体证据缺口 |
| 7 | 刷新页面、切换语言、退出再登录 | 账号和持久化记录可恢复；新任务按所选语言生成 | 前端、API、Origin、Cookie 主机名 |

当前业务接口需要登录，直接匿名请求 `/api/v1/papers`、`/paper-search`、`/tasks` 返回 401 不代表启动失败。首次验收优先使用前端，不要直接套用账号功能上线前的匿名 PowerShell 示例。

### 0.11 以后如何重启和安全停止

首次成功后，不需要每天重新安装依赖、生成密钥、新建数据库或执行清库。

**日常重启数据库，Windows，项目根目录：**

~~~powershell
Set-Location .\backend
docker compose -p acs-local up -d --wait postgres
Set-Location ..
~~~

**日常重启数据库，macOS，项目根目录：**

~~~bash
cd ./backend
docker compose -p acs-local up -d --wait postgres
cd ..
~~~

随后重新打开第 0.9 节的六个终端，再执行第 0.10 节的健康检查。只有代码新增迁移时才先停止 API 和 Worker，执行第 0.8 节升级，再重新启动。依赖或锁文件变化时重新执行第 0.3 节的依赖安装，已有 `.env` 不会被该节覆盖。

停止时先在前端、API、各 Worker 终端按 `Ctrl+C`，等待退出；再在临时终端停止数据库。

**Windows，项目根目录：**

~~~powershell
Set-Location .\backend
docker compose -p acs-local stop postgres
Set-Location ..
~~~

**macOS，项目根目录：**

~~~bash
cd ./backend
docker compose -p acs-local stop postgres
cd ..
~~~

预期：服务终端返回命令提示符，数据库容器停止；数据卷和 `backend/runtime/storage-local` 中的文件保留。不要用 `docker compose down -v` 或删除存储目录作为日常退出方式。

### 0.12 首次启动常见问题（两种系统）

| 现象 | 处理方法与预期 |
| --- | --- |
| 找不到 compose 文件，或 `unknown shorthand flag: d` | 使用本节完整命令；确认已进入 backend，项目名直接写为 acs-local，不使用未赋值的临时变量 |
| Docker 连接失败 | 打开 Docker Desktop，等待 Server 可用后重试；不能只看 Client 版本 |
| 55433 端口被占用 | 在 backend/.env 同时修改 POSTGRES_PORT 和 DATABASE_URL 中的宿主机端口；确认目标后重新启动该 Compose 项目，预期端口映射与连接串一致 |
| PostgreSQL 密码错误、数据库不存在 | 检查是否复用了以前的数据卷，以及 POSTGRES_* 和 DATABASE_URL 是否相符；修改初始化环境不会改写已有数据库用户 |
| 迁移正常但 API 连接了另一套数据库 | 检查进程环境变量是否覆盖 .env，所有终端都必须使用同一套配置 |
| 登录或注册显示 AUTH_UNAVAILABLE | 检查三个密钥、可信前端地址、SMTP 配置；重新执行第 0.6 节的离线格式校验，不要关闭账号校验绕过错误 |
| 注册没有验证邮件 | 确认 Mail Worker 已运行、QQ SMTP 使用授权码且发件地址一致，再看垃圾邮件和 Worker 日志 |
| 论文一直 uploaded | 检查 Parser Worker；API、Import、Parser 连接的库和存储目录必须一致 |
| 任务一直排队 | 检查 Runner Worker，且 TASK_RUNNER=langgraph；健康检查成功不代表 Worker 已启动 |
| 模型调用仍指向旧地址 | 清理系统/终端覆盖，完整退出并重开 VS Code，再重启 API 与 Runner；只改 .env 不会更新已运行进程 |
| arXiv 搜索超时或响应非法 | 保留请求编号并检查 API 日志；先用本地 PDF 继续验证其他功能。Parser/Runner 正常不证明 arXiv 连接正常 |
| 前端端口 5173 已占用 | 停止此前的 Vite 开发服务后重试，不随意改前端端口导致 Origin 和邮件链接不匹配 |

如果确认当前终端继承了旧的数据库或模型配置，可以先移除以下覆盖项，再重新执行第 0.6 节并启动对应进程。**这只影响当前终端，不会删除 Windows 系统环境变量、shell 启动文件中的 export，也不会更新其他已开的终端。**

**Windows PowerShell，项目根目录：**

~~~powershell
Remove-Item -LiteralPath Env:DATABASE_URL,Env:POSTGRES_DB,Env:POSTGRES_USER,Env:POSTGRES_PASSWORD,Env:POSTGRES_PORT,Env:STORAGE_ROOT -ErrorAction SilentlyContinue
Remove-Item -LiteralPath Env:TASK_RUNNER,Env:LLM_BASE_URL,Env:LLM_MODEL_ID,Env:LLM_API_KEY,Env:LLM_THINKING_MODE -ErrorAction SilentlyContinue
~~~

**macOS Terminal，项目根目录：**

~~~bash
unset DATABASE_URL POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_PORT STORAGE_ROOT
unset TASK_RUNNER LLM_BASE_URL LLM_MODEL_ID LLM_API_KEY LLM_THINKING_MODE
~~~

要让之后的新终端也持续使用 `.env`，Windows 需在系统的用户/系统环境变量设置中移除不再需要的旧覆盖；macOS 需检查并手动移除 shell 启动文件（例如 `~/.zshrc`、`~/.zprofile` 或 `~/.bash_profile`）中对应的旧 export。随后完全退出 VS Code/相关终端应用并重新打开，再新建服务终端。其他 AUTH_*、SMTP_*、ARXIV_* 等配置也遵循相同的优先级；只移除确认属于本项目的旧覆盖，不批量清理其他项目配置。

## 1. 每次启动看这里

本节到后续测试章节保留此前 Windows 本机验收环境的用法。使用第 0 节新建的 acs-local 数据库时，日常启停按第 0.11 节操作，**不要改用第 2.1 节的历史验收项目**；六个服务的命令与第 0.9 节一致。macOS 使用第 0 节的 Terminal 版本。

先打开 Docker Desktop，等待引擎就绪，然后完成第 2 节的数据库检查。接着在 VS Code 中分别新建六个终端，执行第 3 节的对应命令。每个常驻进程独占一个终端，保持窗口运行。

| 终端 | 服务 | 作用 | 何时需要 |
| --- | --- | --- | --- |
| 1 | API | 提供账号、论文、任务等接口 | 始终需要 |
| 2 | Parser Worker | 解析上传或导入的 PDF | 上传、导入论文时需要 |
| 3 | Runner Worker | 调用真实模型生成摘要、问答、综述 | 真实研究任务需要 |
| 4 | Import Worker | 下载 arXiv PDF、保存来源和导入状态 | arXiv 导入需要 |
| 5 | Mail Worker | 发送验证邮箱、找回密码邮件 | 注册、重发验证、密码找回需要 |
| 6 | 前端 | 提供浏览器页面 | 页面操作需要 |
| 临时终端 | 检查与测试 | 执行健康检查、迁移和回归命令 | 用完可以关闭 |

只测试本地上传、真实研究且已有可登录账号时，可以暂不启动 Import 和 Mail Worker。首次注册需要正确的 SMTP 配置和 Mail Worker。只有 arXiv 搜索、不下载 PDF 时，不依赖 Import Worker。

日常打开项目无需重新安装依赖、重新设置环境变量或清空数据。配置保存到 backend/.env，见第 5 节。

## 2. 启动数据库并检查迁移

### 2.1 当前本机已有的数据库

本机此前验收使用的 Compose 项目名是 acs-mvp3-acceptance-e379b08d，端口为 55432，数据库和用户均为 literature_acceptance。下面直接使用完整项目名，不依赖其他终端中的 $acceptanceProject 变量。

在临时终端执行：

~~~powershell
Set-Location .\backend
docker version
docker compose version
docker compose -p acs-mvp3-acceptance-e379b08d up -d --wait postgres
docker compose -p acs-mvp3-acceptance-e379b08d ps
uv run --locked alembic current
uv run --locked alembic check
~~~

预期：postgres 显示 healthy；升级本次跨语言检索功能后，迁移版本为 20261115_0005 (head)；结构检查输出 No new upgrade operations detected.。尚未升级时先按第 2.2 节操作。Docker 的 -d 表示后台运行，因此这个终端可以继续输入命令。

这里的 Compose 项目名仅适用于当前本机；backend/.env 中的 POSTGRES_*、DATABASE_URL 应继续指向原来的数据库。不要在已有项目上随意切换 Compose 项目名，否则可能创建另一套空卷，或发生端口冲突。

### 2.2 拉取代码后有新迁移

停止 API 和所有后端 Worker 后，确认数据库目标，再执行：

~~~powershell
Set-Location .\backend
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
~~~

确认成功后，再启动第 3 节的服务。不要为了消除迁移错误直接删除数据库。账号迁移 20261114_0004 对旧业务数据有保护检查；如果提示拒绝迁移，先阅读 [后端文档第 10 节](../backend/README.md#10-账号qq-邮件与私有数据2026-11-14)。当前本机此前已完成该迁移，无需重复清理旧数据。

20261115_0005 仅扩展任务恢复约束，允许新的摘要、问答和综述工作流保留原始截止时间后恢复，不清除数据、不增加数据表。已有 0004 数据库可直接升级；不要执行旧账号迁移的数据清理流程。重启 API 与所有 Worker，前端刷新后新建任务即可使用新检索策略。历史任务保留原策略，不会自动重新生成结果。现有模型配置可继续使用，无需新增服务。

## 3. 六个常驻终端：逐个复制执行

以下按真实模型模式编写。配置缺失时先完成第 5 节；后端六类进程读取同一份 backend/.env，必须使用相同的数据库、存储路径及相关密钥。

### 终端 1：API 服务

~~~powershell
Set-Location .\backend
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
~~~

预期出现 Uvicorn running on http://127.0.0.1:8000 和应用启动完成日志。此终端保持运行。--reload 用于本地开发；它只负责重新加载 API，不会替其他 Worker 重新加载配置。

### 终端 2：PDF 解析 Worker

~~~powershell
Set-Location .\backend
uv run --locked python -m app.parser_worker
~~~

负责将 PDF 从 uploaded 推进到解析完成的 ready 状态。空闲时可能没有新输出；用上传后的解析状态确认工作是否正常。目前支持文本 PDF，不包含扫描件 OCR。

### 终端 3：真实研究 Runner Worker

~~~powershell
Set-Location .\backend
uv run --locked python -m app.runner_worker
~~~

需要 TASK_RUNNER=langgraph 以及完整模型配置。新任务的进度应从排队进入执行，最终完成或显示具体错误。此进程会调用已配置的模型服务，可能产生费用。摘要、问答和多篇论文综述均使用服务端自动预算，无需在页面或每个终端手工配置任务预算。RESEARCH_* 服务器上限有默认值，已有 .env 无需新增即可运行；修改后重启 API 与 Runner，仅影响新任务。

### 终端 4：arXiv 导入 Worker

~~~powershell
Set-Location .\backend
uv run --locked python -m app.import_worker
~~~

需要 ARXIV_ENABLED=true 和有效 ARXIV_CONTACT_EMAIL。负责下载和保存 PDF，后续文本解析由终端 2 完成。导入 succeeded 与论文 ready 是两个阶段，不应只看导入状态判断解析是否完成。

### 终端 5：邮件 Worker

~~~powershell
Set-Location .\backend
uv run --locked python -m app.mail_worker
~~~

需要正确的账号密钥、邮件加密密钥及 QQ SMTP 配置。API 只将邮件写入持久化队列，真正发送由这个进程完成；终端无持续输出不等于发送失败，请结合收件箱及流程结果检查。

这是实际投递进程，并非只检查配置的测试命令。以下单次命令最多处理一封可领取邮件，也可能真实发送；运行时先停止同一队列的常驻 Mail Worker，便于观察：

~~~powershell
Set-Location .\backend
uv run --locked python -m app.mail_worker --once
~~~

单次命令结束不证明一定发出了邮件，队列可能为空。真实投递需通过自己控制的测试收件邮箱验收。

### 终端 6：前端页面

~~~powershell
Set-Location .\frontend
npm.cmd run dev
~~~

浏览器打开 http://127.0.0.1:5173。默认端口固定为 5173，占用时会报错。前端通过 Vite 将 /api、/health、/ready 转发到本地 8000 端口。

### 可选：Mock Worker 替代真实 Runner

无需模型调用、只验证模拟任务流程时，将 backend/.env 中 TASK_RUNNER 改为 mock，重启 API，然后启动：

~~~powershell
Set-Location .\backend
uv run --locked python -m app.worker
~~~

Mock Worker 和真实 Runner 领取不同类型的任务。更改 TASK_RUNNER 只影响之后新建任务；已创建的真实任务不能靠 Mock Worker 完成。模拟结果不能用于证明真实分析或引用质量。

## 4. 每次启动后的快速检查

### 4.1 API 存活与数据库就绪

在临时终端执行，目录不限：

~~~powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 10 | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/ready' -TimeoutSec 10 | ConvertTo-Json -Compress
~~~

预期分别为 {"status":"ok"} 和 {"status":"ready"}。它们不证明 Worker 已运行，也不证明模型、arXiv 或邮件服务可用。

### 4.2 查看生效配置，不输出密钥

~~~powershell
Set-Location .\backend
uv run --locked python -c "from app.config import Settings; s=Settings(); print('Runner:', s.task_runner); print('Base URL:', s.llm_base_url); print('Model:', s.llm_model_id); print('Thinking mode:', s.llm_thinking_mode); print('API key set:', bool(s.llm_api_key and s.llm_api_key.get_secret_value())); print('Real runner configured:', s.real_runner_configured); print('arXiv configured:', s.arxiv_configured); print('SMTP configured:', s.smtp_configured); print('Frontend URL:', s.frontend_public_url)"
~~~

真实研究预期 Runner 为 langgraph，Real runner configured 为 True；真实搜索/导入预期 arXiv configured 为 True；注册和找回邮件需要 SMTP configured 为 True。这些布尔值只是配置完整性检查，不会发起外部请求，不能替代服务连通和投递验收。

### 4.3 浏览器人工验收顺序

1. 使用 http://127.0.0.1:5173 注册账号，检查验证邮件，完成验证后登录。已有账号可直接登录。
2. 上传一份文本 PDF，等待论文状态 ready，检查页数、标题和本地 PDF 打开是否正常。
3. 用这篇论文创建摘要任务，观察排队、执行、完成状态，抽查引用与 PDF 页码。
4. 创建论文问答；没有直接证据时，允许返回证据不足，不能将其视为通用聊天回答。
5. 使用 arXiv 搜索并导入另一篇论文，分别检查导入完成、解析完成与来源信息。
6. 选择多篇已解析论文创建综述，检查正文、比较表、引用，刷新页面确认记录恢复。
7. 切换中英文界面，检查页面文案；既有研究正文不会因界面切换自动翻译，新任务需选择预期输出语言。
8. 退出后注册并登录另一个账号，确认论文库和研究记录互相隔离；测试找回密码与重置后重新登录。

现在业务接口需要账号登录。以前直接执行匿名 /api/v1/papers、/paper-search、/tasks 等命令可能返回 401。手工验收优先通过前端完成；如自行编写 PowerShell API 调用，需保留登录 Cookie，会话内写请求还需正确的 Origin、X-CSRF-Token，以及对应接口要求的幂等头。不要把旧的匿名请求作为服务故障判断依据。

## 5. 首次安装与持久化配置

本节只在新环境、依赖更新或配置改变时使用。当前已有 backend/.env 时不要复制模板覆盖它。

### 5.1 依赖与配置文件

需要 Python 3.11+、uv、Docker Desktop，以及符合 frontend/package.json 要求的 Node.js：^20.19.0 或 >=22.12.0。

~~~powershell
Set-Location .\backend
uv sync --locked
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Set-Location ..
Set-Location .\frontend
npm.cmd ci
~~~

首次新建数据库时，在 backend/.env 中配置匹配的 DATABASE_URL 与 POSTGRES_*。若采用模板默认的新环境，可在 backend 目录执行 docker compose up -d --wait postgres，再按第 2.2 节迁移。当前本机继续使用第 2.1 节的已有项目，不要改成模板默认的 5432 数据库。

### 5.2 在 backend/.env 中保存配置

用 VS Code 编辑文件，一行一个变量。下面是配置结构示例，含占位值，不能整段覆盖现有文件；实际账号、联系方式与密钥只保存在本机 .env 中。

~~~dotenv
TASK_RUNNER=langgraph
RESEARCH_CONTEXT_TOKENS=32768
RESEARCH_OUTPUT_TOKENS=8192
RESEARCH_TASK_TOKENS=100000
RESEARCH_CALL_TIMEOUT_SECONDS=180
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_ID=deepseek-flash
LLM_API_KEY=填写你自己的模型服务密钥
LLM_THINKING_MODE=disabled
ARXIV_ENABLED=true
ARXIV_CONTACT_EMAIL=your-contact@example.com
FRONTEND_PUBLIC_URL=http://127.0.0.1:5173
AUTH_COOKIE_SECURE=false
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USERNAME=你的完整QQ邮箱地址
SMTP_FROM=与SMTP_USERNAME相同的完整QQ邮箱地址
SMTP_AUTH_CODE=QQ邮箱的SMTP授权码
~~~

模型地址和 ID 是此前选择的配置，需与自己账号实际可用的服务匹配。QQ SMTP 使用授权码，不是邮箱登录密码；用户注册邮箱不限 QQ。

AUTH_RATE_KEY、AUTH_CSRF_KEY、MAIL_OUTBOX_KEY 已在当前本机私有配置中生成，应保持稳定。新机器需按 [后端账号配置说明](../backend/README.md#101-配置与会话) 分别生成两个独立随机账号密钥和一个 Fernet 邮件密钥。不能用示例占位符启动，也不要每次启动重新生成，特别是队列还有加密邮件时。

截至最近一次配置检查，真实 QQ SMTP 尚未配置完成。若第 4.2 节显示 False，先补齐上述三个 SMTP 字段，再重启 API 和 Mail Worker，并完成自己邮箱的实际收信测试。

所有后端终端通常无需重复输入 $env:...。修改 .env 后重启读取该配置的 API/Worker；普通 Python Worker 不会自动重载。不要打印、截图或提交 .env，也不要把后端密钥放进前端的 VITE_* 变量。

### 5.3 .env 改了却没有生效

进程环境变量优先于 .env；VS Code 新终端会继承 VS Code 启动时的环境。检查第 4.2 节输出，如果仍指向旧模型地址，可在即将启动后端进程的当前终端中移除旧覆盖：

~~~powershell
Remove-Item -LiteralPath Env:LLM_BASE_URL -ErrorAction SilentlyContinue
Remove-Item -LiteralPath Env:LLM_MODEL_ID -ErrorAction SilentlyContinue
Remove-Item -LiteralPath Env:LLM_THINKING_MODE -ErrorAction SilentlyContinue
Remove-Item -LiteralPath Env:TASK_RUNNER -ErrorAction SilentlyContinue
~~~

随后重新检查生效配置并启动进程。这只清理当前终端继承的四个覆盖项，不会改写 .env 或系统环境。若在 Windows 系统环境中已删除旧配置，完全退出所有 VS Code 窗口后重新打开，再创建终端；已运行的旧 Worker 仍须停止并重新启动。

## 6. 自动化检查与测试

这些命令是一次性检查，执行后退出。无需与常驻服务放在同一终端，也不要把 Mail Worker 当成无副作用测试。

### 6.1 后端默认测试

~~~powershell
Set-Location .\backend
uv run --locked python -B -m unittest discover -s tests -q
~~~

默认测试中有依赖专用环境变量的门控套件，可能显示 skipped；应检查退出码和失败信息，跳过不代表对应原生数据库检查已通过。测试使用夹具或替身，不以真实模型、arXiv 或 QQ 邮件作为验收目标。

### 6.2 账号与资源隔离的原生 PostgreSQL 测试

先启动本机 PostgreSQL，确认 backend/.env 的 DATABASE_URL 指向预期的本地实例，连接账号具有创建和删除测试数据库权限，再依次执行：

~~~powershell
Set-Location .\backend
uv run --locked python -B tests/test_auth.py --postgres
uv run --locked python -B tests/test_ownership.py --postgres
~~~

这两个入口根据本地连接配置创建随机命名的 auth_tests_<UUID>、ownership_tests_<UUID> 隔离数据库，测试后自动删除各自创建的测试库；不应手工改为业务库。脚本使用测试邮件和模型替身，不发送真实 QQ 邮件。需要 PostgreSQL 的完整账号与隔离验证时，运行它们，而非只看默认 discover 的跳过结果。

### 6.3 综述逻辑与原生数据库检查

不需要真实模型的综述逻辑检查：

~~~powershell
Set-Location .\backend
uv run --locked python -B -m unittest discover -s tests -p test_staged_review.py -v
uv run --locked python -B -m unittest discover -s tests -p test_review_execution.py -v
~~~

原生综述套件 tests/test_review_postgres.py 另需 STAGED_REVIEW_TEST_URL，且强制要求隔离库名 review_tests、主机 127.0.0.1、端口 55432 或 55433。不要将 DATABASE_URL 的业务库直接作为测试目标。以下仅适用于第 2.1 节当前本机实例，首次建立专用测试库：

~~~powershell
Set-Location .\backend
docker compose -p acs-mvp3-acceptance-e379b08d exec -T postgres psql -v ON_ERROR_STOP=1 -U literature_acceptance -d postgres -c 'CREATE DATABASE review_tests;'
~~~

若提示已存在，先确认该库确实专用于测试，不要删除或覆盖未知数据库。确认是隔离测试库后，在同一终端设置测试连接并执行：

~~~powershell
Set-Location .\backend
$env:STAGED_REVIEW_TEST_URL = uv run --locked python -c "from app.config import Settings; from sqlalchemy.engine import make_url; print(make_url(Settings().database_url.get_secret_value()).set(database='review_tests').render_as_string(hide_password=False))"
uv run --locked python -B -m unittest discover -s tests -p test_review_postgres.py -v
Remove-Item -LiteralPath Env:STAGED_REVIEW_TEST_URL -ErrorAction SilentlyContinue
~~~

第一条赋值将含凭据的连接字符串保存在当前进程环境中，不要回显该变量。套件会迁移并使用专用测试库；此入口不会自动创建或删除整个 review_tests 数据库。业务进程继续使用原 DATABASE_URL，不需改动 .env。其他环境需自行准备满足上述保护条件的隔离库。

### 6.4 前端类型、构建与综述检查

~~~powershell
Set-Location .\frontend
npm.cmd run typecheck
npm.cmd run build
npm.cmd run verify:review
~~~

build 已包含 typecheck；只需要常规验证时，执行 build 与 verify:review 即可。构建成功不证明真实后端、邮件和模型已通过联调。

### 6.5 账号页面离线浏览器测试（可选）

需要 Python Playwright 和 Chromium。首次在项目根目录安装到独立测试环境：

~~~powershell
uv venv runtime/browser-venv
uv pip install --python runtime/browser-venv/Scripts/python.exe playwright
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location).Path 'runtime/pw-browsers'
& '.\runtime\browser-venv\Scripts\python.exe' -m playwright install chromium
~~~

已有该测试环境时跳过安装。另开一个专用预览终端，保持运行：

~~~powershell
Set-Location .\frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5193 --strictPort
~~~

再在测试终端执行：

~~~powershell
$env:AUTH_PREVIEW_URL = 'http://127.0.0.1:5193'
& '.\runtime\browser-venv\Scripts\python.exe' frontend/checks/auth-browser.py
Remove-Item -LiteralPath Env:AUTH_PREVIEW_URL -ErrorAction SilentlyContinue
~~~

脚本模拟账号及业务 API，覆盖注册、验证、登录、退出、会话清理和响应式布局，不连接真实后端、不发送邮件、不调用模型。5193 仅供该隔离测试，日常账号操作仍用 5173；不需要为此修改 FRONTEND_PUBLIC_URL。旧 workspace-browser.py、review-browser.py 使用匿名夹具，不能直接代替当前账号验收，适配要求见 [前端文档](../frontend/README.md)。

## 7. 停止、重启与常见问题

### 正常停止与重新启动

- 停止某个常驻进程：切换到对应终端按 Ctrl+C，等待进程退出。关闭终端不等于删除数据。
- 修改模型配置：重启 API 和 Runner Worker；修改账号、SMTP 或共享密钥配置：重启 API、Mail Worker 及受影响进程。修改公共配置时统一重启后端进程更容易保持一致。
- 停止全部应用：逐一停止前端、API 和 Worker；数据库可以继续运行。重新使用时按第 2、3 节启动。
- 如需停止数据库，先停止全部依赖它的进程，再执行下面命令；下次通过第 2.1 节 up 恢复。

~~~powershell
Set-Location .\backend
docker compose -p acs-mvp3-acceptance-e379b08d stop postgres
~~~

正常启停不需要 down -v、数据库重置或清空 STORAGE_ROOT。数据重置另见 [后端文档第 10.4 节](../backend/README.md#104-已有开发库的受控重置)，不要将其加入日常启动流程。

### 按现象定位

| 现象 | 优先检查 |
| --- | --- |
| Docker 无法连接 | Docker Desktop 是否已启动且引擎就绪；用 docker version 检查 Server 部分 |
| unknown shorthand flag: 'd' in -d | 检查 Compose 版本与 -p 参数是否有值；用本文完整项目名命令，避免未定义的 $acceptanceProject |
| /ready 失败或数据库拒绝连接 | 检查容器 healthy、DATABASE_URL、端口与迁移；不要切换到另一空库 |
| API 正常，研究任务一直排队 | 检查任务类型对应的 Runner 或 Mock Worker，确认与 API 使用相同数据库 |
| PDF 一直 uploaded | Parser Worker 是否运行；查看该终端错误及论文状态 |
| 导入一直 queued | Import Worker 是否运行、arXiv 配置是否完整、是否与 API 使用同一数据库 |
| arXiv 超时或响应不合法 | 查看界面错误和请求编号；稍后重试或先上传本地 PDF。Import Worker 不负责修复搜索服务的上游响应 |
| 注册/找回无法收信 | 检查 SMTP configured、完整发件地址与授权码、Mail Worker、垃圾邮件箱和邮件链接有效期；统一受理提示不代表邮件已送达 |
| AUTH_UNAVAILABLE | 检查两个独立账号密钥、邮件加密密钥及账号配置，不只看 /health |
| 401 或 CSRF 校验失败 | 重新登录，统一使用 127.0.0.1:5173，核对 FRONTEND_PUBLIC_URL；检查是否仍使用旧匿名 API 命令 |
| 真实任务 AGENT_EXECUTION_FAILED | 查看 Runner 终端同一 task_id 附近日志和第 4.2 节实际生效模型地址、模型 ID；不要只确认 API 存活 |
| INVALID_AGENT_RESULT | 保存任务 ID、具体错误和 Runner 日志，区分 JSON 截断与证据校验；单纯重启不能证明问题已解决 |
| npm.ps1 被执行策略阻止 | 使用本文的 npm.cmd 命令 |
| 8000 / 5173 端口占用 | 找到之前的 API / 前端终端并 Ctrl+C；不要随意改变前端端口，否则账号 Origin 和邮件链接也需同步调整 |
| PowerShell 中文乱码 | 在受影响终端设置下方 UTF-8 编码后重新请求；已损坏的旧变量需重新获取 |

~~~powershell
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
~~~

仍有乱码时，优先通过前端或浏览器开发者工具查看原始响应；终端编码设置不能修复已经错误解码的内容。

排查时记录：使用的页面功能、任务 ID 或请求编号、发生时间、对应 Worker 日志，以及第 4.2 节不含密钥的输出。避免粘贴密码、Authorization、Cookie、CSRF 或邮件令牌。

## 跨语言检索更新后的验收

先按第 2.2 节升级到 20261115_0005，再重启第 3 节的 API 和后端 Worker，刷新前端。无需修改已有模型变量；新建任务使用新策略，旧结果不会自动更新。

1. 对一篇已就绪英文论文创建问答：“这篇论文要解决什么问题？作者提出了什么方法，主要结论是什么？”检查回答及引用。
2. 询问一个论文中有原文支持的具体实验数字，检查数字、上下文和页码。
3. 询问一个论文未覆盖的问题，确认显示当前证据不足，不编造数字，也不直接断言全文不存在该信息。
4. 创建六篇论文的中文综述，检查每篇参与比较，空单元格显示“当前证据未覆盖”。
5. 在执行记录中检查跨语言扩展、证据选择、必要时的补检索记录；如扩展降级，应有明确 warning。
6. 新建摘要，要求概括方法、创新点和局限性。首次证据不足且找到新窗口时应出现一次补检记录；若仍显示部分可回答，提示下方应列出具体缺失项。
7. 打开已有的部分综述，检查提示按论文标题列出缺失维度；切换界面语言后固定维度标签同步切换，模型生成说明保留任务语言。

证据覆盖补检与缺口展示改进无需再次迁移数据库。分别在现有 API 和研究 Runner 终端按 Ctrl+C，然后从项目根目录重新执行（两个独立终端）：

~~~powershell
Set-Location .\backend
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
~~~

~~~powershell
Set-Location .\backend
uv run --locked python -m app.runner_worker
~~~

刷新前端并新建任务；已有结果不会自动重新生成。PDF Parser、导入和邮件 Worker 按需保持运行。研究 Runner 终端必须保持运行，否则新研究任务只会排队。

本地回归（从项目根目录开始；不调用真实模型）：

~~~powershell
Set-Location .\backend
uv run --locked python -B -m unittest discover -s tests -q
uv run --locked python -B tests/test_ownership.py --postgres
Set-Location ..\frontend
npm.cmd run verify:review
npm.cmd run build
~~~

PostgreSQL 回归会创建并清理本次随机测试库，保留业务库。浏览器诊断测试需本地已有 Playwright 环境；脚本 frontend/checks/retrieval-browser.py 默认访问 127.0.0.1:5194，全部 API 为本地夹具。

## 独立 Agent 后端适配（2026-11-18）

本节是新增模式，不替换上文现有服务的启动步骤。完整协议见 [Agent 对接](agent-backend-integration.md)。第 1/2 阶段历史测试命令保留；第 3.1–3.3 阶段的本地与 TACC 自动派发、恢复及统一验收见本文件末尾。部署与模型配置完成前不要切换真实演示环境。

以下命令从项目根目录开始；离线测试不要求启动数据库、模型或 TACC。Windows PowerShell：

~~~powershell
Push-Location .\backend
uv run --locked python -B -m unittest discover -s tests -p "test_agent_bridge.py" -v
Pop-Location
~~~

macOS：

~~~bash
(cd backend && uv run --locked python -B -m unittest discover -s tests -p "test_agent_bridge.py" -v)
~~~

预期：后端协议、PDF 输入包、来源映射与结果校验用例通过。这组测试只验证后端；Agent 本地来源测试见下文，TACC 端到端验收仍待完成。

### Agent 第 1 阶段离线测试

以下命令从项目根目录执行，不启动服务、不调用真实模型或搜索、不访问数据库。首次执行 sync 会安装锁定的 Agent Python 3.12 与开发依赖。现有 Agent 使用 `--frozen` 安装锁文件；不要为运行本阶段测试自动更新锁文件。

Windows PowerShell：

```powershell
uv sync --project .\agent --frozen --group dev
uv run --project .\agent --frozen python -B -c "import os; os.environ.pop('AGT_TEST_DATABASE', None); os.chdir('agent'); import pytest; raise SystemExit(pytest.main(['-q']))"
```

macOS：

```bash
uv sync --project ./agent --frozen --group dev
uv run --project ./agent --frozen python -B -c "import os; os.environ.pop('AGT_TEST_DATABASE', None); os.chdir('agent'); import pytest; raise SystemExit(pytest.main(['-q']))"
```

预期：离线测试通过；数据库实测跳过，不能创建符号链接的系统还会跳过对应测试。覆盖原始 PDF 解析、物理页码、授权清单、文件摘要、缓存复核、本地阅读/摘要/引用和原有 arXiv 行为。测试使用临时合成 PDF 与脚本模型，不代表真实研究质量或 TACC 已验收。本地真实执行入口见 [Agent README](../agent/README.md#授权本地-pdf)，当前无需为此启动新服务。

后续进入数据库联调时，先停止 API 和研究 Worker，再执行新增迁移。Windows：

~~~powershell
Push-Location .\backend
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
Pop-Location
~~~

macOS：

~~~bash
(cd backend && uv run --locked alembic upgrade head)
(cd backend && uv run --locked alembic current)
(cd backend && uv run --locked alembic check)
~~~

预期 head 为 `20261120_0007`，check 无新增操作。迁移兼容 main 元数据旧库和历史 Agent 旧库，不清除历史数据；不要手工 stamp 或删表。

完成末尾 local 或 tacc 传输配置后，在 backend/.env 配置 TASK_RUNNER=agent、AGENT_DISPATCH_ENABLED=true。研究 Worker 仍使用同一个入口；每个命令在独立终端中从根目录执行：

~~~powershell
Push-Location .\backend
uv run --locked python -m app.runner_worker
Pop-Location
~~~

~~~bash
(cd backend && uv run --locked python -m app.runner_worker)
~~~

它不调用旧后端模型逻辑。manual 模式需要外部投递；local/tacc 由适配器调度。后台任务进入 running 仅表示派发 Worker 已领取，不能据此判断 TACC 作业已经运行。

原生 PostgreSQL 测试位于 backend/tests/test_agent_postgres.py，默认跳过。只可对事先创建的、库名为 agent_bridge_tests 或 agent_bridge_tests_<32位小写十六进制> 的本机专用空库设置 AGENT_TEST_DATABASE_URL。测试会迁移并清空该库中的业务表，禁止使用开发库、验收库或生产库；当前未替你创建或运行该测试库。


### Agent 第 2 阶段：远程作业入口

本节命令全部从项目根目录开始。先运行离线测试即可，不需要开启新服务、修改 backend/.env 或迁移数据库。

Windows PowerShell：

~~~powershell
uv sync --project .\agent --frozen --group dev
uv run --project .\agent --frozen python -B -c "import os; os.environ.pop('AGT_TEST_DATABASE', None); os.chdir('agent'); import pytest; raise SystemExit(pytest.main(['tests/test_dispatch_bundle.py', 'tests/test_dispatch_job.py', '-q']))"
uv run --project .\agent --frozen python agent/run_dispatch.py --help
~~~

macOS：

~~~bash
uv sync --project ./agent --frozen --group dev
uv run --project ./agent --frozen python -B -c "import os; os.environ.pop('AGT_TEST_DATABASE', None); os.chdir('agent'); import pytest; raise SystemExit(pytest.main(['tests/test_dispatch_bundle.py', 'tests/test_dispatch_job.py', '-q']))"
uv run --project ./agent --frozen python agent/run_dispatch.py --help
~~~

预期：65 个入口/协议用例通过，帮助信息列出 --input、--dispatch-id、--input-sha256、--work-root、--output-dir 等参数。测试使用合成 PDF 和脚本模型，不访问真实模型、搜索、数据库或 TACC；macOS 命令按平台语法提供，当前仅在 Windows 上实测。

**以下是真实作业运行模板，当前无需执行。** 等远程部署或明确开展本地真实 Agent 联调时使用。先在 Agent 环境配置模型，并把后端生成的 input.zip 放到 `runtime/agent-input/<dispatch_id>/input.zip`。dispatch_id 与 input_sha256 从可信后端派发记录获取；不要仅计算未知 ZIP 自带 manifest 的摘要后就将其视为可信。此入口会调用真实模型，可能产生费用。

Windows PowerShell（替换尖括号占位值）：

~~~powershell
$dispatchId = "<后端返回的 dispatch_id>"
$inputSha256 = "<后端返回的 input_sha256>"
$inputBundle = ".\runtime\agent-input\$dispatchId\input.zip"
$outputDirectory = ".\runtime\agent-output\$dispatchId"
uv run --project .\agent --frozen python agent/run_dispatch.py --input "$inputBundle" --dispatch-id "$dispatchId" --input-sha256 "$inputSha256" --work-root .\runtime\agent-work --output-dir "$outputDirectory"
$jobExitCode = $LASTEXITCODE
"Agent exit code: $jobExitCode"
Get-Content "$outputDirectory\status.json" -Raw -Encoding UTF8 | ConvertFrom-Json | Select-Object state, stop_reason, error
~~~

macOS（替换尖括号占位值）：

~~~bash
dispatch_id="<后端返回的 dispatch_id>"
input_sha256="<后端返回的 input_sha256>"
input_bundle="./runtime/agent-input/$dispatch_id/input.zip"
output_directory="./runtime/agent-output/$dispatch_id"
uv run --project ./agent --frozen python agent/run_dispatch.py --input "$input_bundle" --dispatch-id "$dispatch_id" --input-sha256 "$input_sha256" --work-root ./runtime/agent-work --output-dir "$output_directory"
job_exit_code=$?
printf 'Agent exit code: %s\n' "$job_exit_code"
python3 -c 'import json,sys; s=json.load(open(sys.argv[1],encoding="utf-8")); print({k:s.get(k) for k in ("state","stop_reason","error")})' "$output_directory/status.json"
~~~

预期：status.json 保留，state 只新写 running/succeeded/failed。退出码 0 时研究 completed/partial，存在完整 result.json 和 state=succeeded 的状态文件；partial 仍保留未解决项。退出码 1 时 state=failed，仍有完整研究结果，具体原因看 stop_reason。退出码 2 表示包装器或本次调用错误，通常只有脱敏失败状态；路径无效或锁冲突时可能无法创建新状态文件，此时看终端安全错误代码，BUSY 等调用错误不会覆盖已有作业状态。旧 finished 状态在已有结果通过校验后修正，不会重新调用模型。后端显示“已完成”还需等待结果回收、校验和保存。

结果必须由可信桥接下载并原子发布到后端 inbox/<dispatch_id>/result.json；status.json 不能代替结果。第 3 阶段已接入状态失败映射与自动适配器。重复运行相同已完成输入会复用结果；遇到 BUSY、INCOMPLETE、PREVIOUS_FAILURE 或 OUTPUT_CONFLICT 时先排查，不要删除锁或覆盖结果强行重跑，需要重新执行时显式新建任务。

## Agent 第 3.1–3.3 阶段：统一启动与验收

所有本机命令从项目根目录执行；远程命令会明确标注。配置写进 backend/.env 或 Agent 所在环境的 .env，避免每次开终端重复设置。2026-11-20 合并 main 后，数据库须按上文升级到唯一 head `20261120_0007`。下列真实部署、服务启动、数据库与清理命令由操作者在统一验收时执行，开发过程不会自动替你执行。

### 1. 先完成离线自动检查

Windows PowerShell：

~~~powershell
uv sync --project .\agent --frozen --group dev
uv sync --project .\backend --locked
uv run --project .\backend --locked python -B -c "import os,unittest; [os.environ.pop(k,None) for k in ['OWNERSHIP_TEST_DATABASE_URL','AUTH_TEST_DATABASE_URL','STAGED_REVIEW_TEST_URL','AGENT_TEST_DATABASE_URL']]; s=unittest.defaultTestLoader.discover('backend/tests'); r=unittest.TextTestRunner(verbosity=1).run(s); raise SystemExit(not r.wasSuccessful())"
uv run --project .\agent --frozen python -B -c "import os; os.environ.pop('AGT_TEST_DATABASE',None); os.chdir('agent'); import pytest; raise SystemExit(pytest.main(['-q']))"
~~~

macOS：

~~~bash
uv sync --project ./agent --frozen --group dev
uv sync --project ./backend --locked
uv run --project ./backend --locked python -B -c "import os,unittest; [os.environ.pop(k,None) for k in ['OWNERSHIP_TEST_DATABASE_URL','AUTH_TEST_DATABASE_URL','STAGED_REVIEW_TEST_URL','AGENT_TEST_DATABASE_URL']]; s=unittest.defaultTestLoader.discover('backend/tests'); r=unittest.TextTestRunner(verbosity=1).run(s); raise SystemExit(not r.wasSuccessful())"
uv run --project ./agent --frozen python -B -c "import os; os.environ.pop('AGT_TEST_DATABASE',None); os.chdir('agent'); import pytest; raise SystemExit(pytest.main(['-q']))"
~~~

预期：离线测试通过，隔离数据库用例跳过。test_agent_roundtrip.py 自动选择 agent/.venv 的 Python，创建合成三页 PDF，运行脚本模型，验证 local 进程及模拟 SSH/Slurm 的真实 JSON/文件往返；不连接网络，不使用真实模型、账号或数据库。未安装 Agent 环境时该跨环境用例会跳过，此时不能算完整离线闭环验证。

### 2. 先配置 local 模式

在 backend/.env 设置：

~~~dotenv
TASK_RUNNER=agent
AGENT_DISPATCH_ENABLED=true
AGENT_TRANSPORT=local
AGENT_LOCAL_ROOT=../agent
AGENT_LOCAL_PYTHON=../agent/.venv/Scripts/python.exe
~~~

macOS 将最后一行改为 AGENT_LOCAL_PYTHON=../agent/.venv/bin/python。这些相对路径从 backend/ 解析，终端命令仍从根目录启动。

在 agent/.env 配置该 Agent 支持的模型参数：MODEL_PROVIDER、MODEL_BASE_URL、MODEL_NAME，以及对应提供方的密钥。MODEL_PROVIDER=tacc 时读取 MODEL_API_KEY（无鉴权的私有模型可用其默认值）；bailian 时读取 BAILIAN_API_KEY。使用实际服务端支持的模型 ID，不直接照抄其他 Runner 的 LLM_*。派发任务不使用 Agent 数据库，不需要为 persist 配置数据库；输入包不包含密钥。

按前文启动数据库、API、前端及需要的 Parser/Import/Mail Worker；研究 Worker 使用下面入口。API 与 Worker 必须读取同一 backend/.env，并先停止旧的研究 Worker。

Windows（每个长期服务使用独立终端）：

~~~powershell
Push-Location .\backend
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
Pop-Location
~~~

~~~powershell
Push-Location .\backend
uv run --locked python -m app.runner_worker
Pop-Location
~~~

macOS：

~~~bash
(cd backend && uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000)
~~~

~~~bash
(cd backend && uv run --locked python -m app.runner_worker)
~~~

预期：新任务 agent.transport=local-process-v1，remote_job_id 为 local:<dispatch_id>；无需手动搬运 ZIP 或启动单次 Agent。completed/partial 校验入库后为 succeeded；部分证据警告和原生 stop_reason 保留。关闭研究 Worker 不会取消独立 Agent；重启后跟踪原 dispatch，原执行超时不重置。

### 3. 准备 TACC SSH 与共享环境

先由平台管理员确认 SSH 登录入口、端口、用户名、主机密钥指纹、CPU 分区/账户，以及登录节点和计算节点共同可见的存储路径。官方参考为 turingaicloud/quickstart；当前适配器使用其底层 SSH/Slurm 能力，不要求后端安装旧版 tcloud。若账号只开放网页或 SDK 网关、无法通过系统 OpenSSH 访问登录节点，应先取得平台允许的 SSH/跳板配置，不能假设任意平台域名都能直连。

在 Windows 的 $HOME/.ssh/config 或 macOS 的 ~/.ssh/config 建立 tacc-research 别名。填写真实值，保留主机密钥校验；有跳板时配置 ProxyJump。首次人工连接前向管理员核对指纹，不使用 StrictHostKeyChecking=no。

~~~sshconfig
Host tacc-research
    HostName <平台SSH登录主机>
    User <平台用户名>
    Port <平台SSH端口>
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30
    StrictHostKeyChecking yes
~~~

Windows/macOS 均可从根目录执行以下只读检查（需先完成可信主机记录与密钥认证）：

~~~text
ssh -o BatchMode=yes tacc-research "command -v python3; command -v sbatch; command -v squeue; command -v sacct; command -v scancel"
~~~

预期：五个程序均存在，SSH 无需交互密码。桥接解释器需 Python 3.11+；若登录节点系统 python3 较旧，可将 AGENT_TACC_PYTHON 配置为远程 Agent 的 .venv/bin/python（3.12）。sacct 必须允许查询本人作业，以便已离开队列的任务和提交结果不明时恢复。登录 shell 需要能找到这些 Slurm 命令；仅交互 shell 的 alias 不生效。

### 4. 打包、上传并部署 Agent

本机从根目录生成白名单部署包，包含当前工作区的运行代码和锁文件，排除 .env、虚拟环境、数据、测试及密钥；不会上传整个仓库。Windows：

~~~powershell
uv run --project .\backend --locked python -m app.agent_bridge.deploy --output .\runtime\agent-runtime.tar.gz
scp .\runtime\agent-runtime.tar.gz tacc-research:agent-runtime.tar.gz
ssh tacc-research
~~~

macOS：

~~~bash
uv run --project ./backend --locked python -m app.agent_bridge.deploy --output ./runtime/agent-runtime.tar.gz
scp ./runtime/agent-runtime.tar.gz tacc-research:agent-runtime.tar.gz
ssh tacc-research
~~~

进入远程 Linux 终端后执行，第一行必须替换为平台确认的共享绝对目录；以下变量仅用于一次部署：

~~~bash
export AGENT_REMOTE_BASE="<登录节点和计算节点共享的绝对目录>"
mkdir -p "$AGENT_REMOTE_BASE/acs-agent" "$AGENT_REMOTE_BASE/acs-agent-jobs"
tar -xzf "$HOME/agent-runtime.tar.gz" -C "$AGENT_REMOTE_BASE/acs-agent"
cd "$AGENT_REMOTE_BASE/acs-agent"
uv sync --frozen --no-dev
cp .env.example .env
cp tacc.example.json tacc.local.json
chmod 600 .env tacc.local.json
~~~

在远程 .env 填写模型配置；确保计算节点能够访问该地址，不能把登录节点的 127.0.0.1 误作计算节点可访问的模型地址。配置 tacc.local.json：workspace_root 为共享的 acs-agent-jobs，agent_root 为共享的 acs-agent，python 为其 .venv/bin/python；partition/account/qos 按平台授权填写，不需要时保留 null。cpus/memory_mb 是 CPU Agent 客户端进程资源，本桥接不启动 GPU 模型服务。模型服务需事先独立部署。

检查路径及入口（不调用模型或提交作业）：

~~~bash
.venv/bin/python -B -c 'import json,pathlib; c=json.load(open("tacc.local.json")); print("Agent:", pathlib.Path(c["agent_root"]).is_dir()); print("Python:", pathlib.Path(c["python"]).is_file()); print("Workspace:", pathlib.Path(c["workspace_root"]).is_dir())'
.venv/bin/python -B run_dispatch.py --help
.venv/bin/python -B tacc_bridge.py --help
pwd
~~~

预期三个检查均为 True，两个入口显示帮助。保存 pwd 输出，供本机 backend/.env 填写远程绝对路径；这属于远程配置，不能写成本机项目相对路径。

### 5. 本机切换 TACC 模式

在 backend/.env 设置实际值：

~~~dotenv
TASK_RUNNER=agent
AGENT_DISPATCH_ENABLED=true
AGENT_TRANSPORT=tacc
AGENT_TACC_HOST=tacc-research
AGENT_TACC_HELPER=<远程agent绝对目录>/tacc_bridge.py
AGENT_TACC_CONFIG=<远程agent绝对目录>/tacc.local.json
AGENT_TACC_PYTHON=<远程agent绝对目录>/.venv/bin/python
AGENT_TRANSPORT_TIMEOUT_SECONDS=30
AGENT_RETENTION_SECONDS=604800
~~~

不在本机配置远程模型密钥。停止并重启 API 与研究 Worker，其他服务按已有说明保留。不要在有未完成任务时切换传输类型；旧任务冻结的类型与 Worker 不一致会明确失败，不会悄悄迁移到另一个执行环境。

新建任务后预期 agent.transport=tacc-ssh-slurm-v1，remote_job_id 为 Slurm 数字 ID；远程目录为 workspace_root/<dispatch_id>/。调度排队仍占用原任务总时限；若集群拥堵，按后端上限配置 AGENT_TIMEOUT_SECONDS，超过时限将失败并补偿取消，不无限等待。本地监督进程与远程计算作业都会校验首次领取时确定的绝对截止时间；排队后已过期的作业不再启动 Agent。请确保数据库、本机和集群系统时钟同步。

### 6. 恢复、补偿取消与保留清理

SSH 短暂中断会退避重试；不要再次点击提交来“恢复”原任务。重启 Worker 跟踪同一 dispatch，提交响应丢失时先核对原作业。AGENT_SUBMISSION_UNCERTAIN 或 AGENT_DUPLICATE_JOBS 应保存任务 ID/dispatch ID，请管理员核对完整作业名，不能删除提交标记强行重跑。

Worker 自带维护循环，处理失败/超时且未交付的作业。需要在服务停机后单独补偿一次时，从本机根目录执行，Windows：

~~~powershell
uv run --project .\backend --locked python -m app.agent_bridge.maintenance
~~~

macOS：

~~~bash
uv run --project ./backend --locked python -m app.agent_bridge.maintenance
~~~

该命令不会主动终止仍为 queued/running 的业务任务。取消暂未确认时继续保留文件并等待下一轮补偿；远程不可达时不能声称已取消，平台自身 walltime 仍是最终执行上限。

先预览超过保留期的终态任务，再决定删除。Windows：

~~~powershell
uv run --project .\backend --locked python -m app.agent_bridge.maintenance --cleanup
# 核对预览后才执行下一条
uv run --project .\backend --locked python -m app.agent_bridge.maintenance --cleanup --apply
~~~

macOS：

~~~bash
uv run --project ./backend --locked python -m app.agent_bridge.maintenance --cleanup
# 核对预览后才执行下一条
uv run --project ./backend --locked python -m app.agent_bridge.maintenance --cleanup --apply
~~~

预期：预览保留文件；apply 仅清理终态且超过本地和远程保留时间的受控任务目录。失败且取消尚未确认的任务不会删除。业务数据库中的结果、原始上传 PDF、其他用户或其他 dispatch 目录不受影响。小型身份清理凭据会保留，用于阻止旧 dispatch 再次执行。清理命令需要读取相应服务的数据库与传输配置，属于维护操作，不是离线测试。

最后按 [统一验收清单](agent-transport-acceptance.md) 一次检查 local、TACC、恢复、失败和清理。离线模拟通过不等于真实集群及模型质量验收通过。
