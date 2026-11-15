# 本地启动、测试与验收操作手册

适用环境：Windows PowerShell、当前仓库，整理日期：2026-11-14。所有命令均在 PowerShell 中执行，目录切换使用相对于项目根目录的路径，不依赖项目所在盘符。

**每个命令块都从项目根目录开始执行**（包含 README.md、backend、frontend、docs 的目录）。在 VS Code 中打开项目根文件夹后，新建终端并确认当前目录。命令块执行后可能停留在 backend 或 frontend；复用该终端执行下一个命令块前，先运行 `Set-Location ..` 返回根目录。运行中的服务终端保持不动，检查命令使用另一个终端。

## 1. 每次启动看这里

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

PostgreSQL 回归会创建并清理本次随机测试库，保留业务库。浏览器诊断测试需本地已有 Playwright 环境；脚本 frontend/checks/search-browser.py 默认访问 127.0.0.1:5194，全部 API 为本地夹具。
