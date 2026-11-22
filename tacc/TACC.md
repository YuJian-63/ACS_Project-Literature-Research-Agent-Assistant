# 在 TACC 上运行网页研究任务

网页把问题和可选的论文 UUID 发给后端。Worker 通过课程平台的 `tcloud` 提交一个 CPU 批作业。作业运行网页选定的 Baseline 或 Extension，通过 HTTPS 读取用户论文库、调用百炼，然后把答案和引用写回 TACC 持久目录。Worker 下载结果并存入 PostgreSQL，网页可从引用打开原 PDF 对应页。[作业入口](research/run_job.py) · [Worker 传输](../backend/src/app/agent_bridge/tcloud.py)

<a id="从头启动本机环境"></a>

## 首次配置：从新账号注册到网页研究

**准备环境。** 安装 Docker Desktop、uv、Node.js 和课程 SDK。按[SDK 初始化步骤](README.md#常用-tcloud-命令)配置自己的课程账号与私钥，运行 `tcloud env ls` 查看环境名。

**只填一份表。** 在仓库根目录运行 `./scripts/local-research configure`。首次运行会生成本机私有的 `.env.local-research`。打开它填写下表，再运行同一命令。脚本安装后端依赖，从组件模板生成或更新 `backend/.env` 和 `agent/.env`，并将两份文件权限设为仅当前用户可读写。

| 填写项 | 用途 |
| --- | --- |
| `SMTP_USERNAME`、`SMTP_AUTH_CODE` | 网站发件邮箱及其客户端授权码，用来发送注册验证邮件。QQ 和 163 自动选用对应的 SMTP 主机与 465 端口。使用 163 时，在网页版「设置 → POP3/SMTP/IMAP」中开启服务并新增授权密码。[网易邮箱说明](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac286624f309a1a7089) |
| `BAILIAN_API_KEY` | 你在百炼工作空间创建的 API key。若工作空间的地址或模型有差异，同表填写 `MODEL_BASE_URL` 和 `MODEL_NAME`。 |
| `ARXIV_CONTACT_EMAIL` | 网页搜索和导入论文时提供给 arXiv 的联系邮箱。首次配置留空会使用发件地址；已有配置会保留原联系人。注册表单中的收件邮箱由注册人自行填写。 |
| `AGENT_TCLOUD_ENV_NAME` | 课程 SDK 列出的作业环境名，默认 `acs-network-probe`。 |
| `TAVILY_API_KEY` | 网页作业通过本机代理调用 Tavily 搜索 arXiv，独立 Agent 也使用此 key。 |
| `AGENT_PERSIST` | `true` 为网页 TACC 任务启用 Agent 数据库写入，默认关闭。 |
| `AGENT_DATABASE_URL` | 网页启用持久化、独立 Agent 开启 `--persist` 时的 PostgreSQL 连接。填 Neon 连接串可写入 Neon，填 `local` 可写入本机开发库的 `agt_baseline` schema。切换影响后续运行，已有记录保存在原库。 |
| `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSIONS` | Retrieval Extension 的嵌入配置，可按需覆盖默认值。 |

首次创建后端配置时，脚本生成本机 PostgreSQL 密码、登录密钥和邮件加密密钥，并启用网页 arXiv 搜索与 TACC 派发。已有开发环境会保留数据库连接、存储路径及现有密钥。修改表单后重新运行 `configure`，再重启服务即可生效。已配置的组件可直接使用 `up`。

**安装前端依赖。** 在仓库根目录运行 `npm --prefix frontend ci`。本阶段的空预选验收使用自己的论文库，网页搜索使用 arXiv 接口。开启搜索的 TACC 作业可用自己的短期令牌调用本机 Tavily 代理。

**准备数据库。** 首次运行或代码带来新迁移时，在备份已有数据后执行：

```sh
(cd backend && docker compose up -d --wait postgres && uv run --locked alembic upgrade head)
```

**注册验收。** 先运行 `./scripts/local-research check-mail`，用邮件 Worker 相同的网络路径验证 TLS 和 SMTP 登录。再按下一节启动服务；如果刚修改了正在运行的服务配置，先结束现有任务，在启动终端按 Ctrl+C 后重新运行。用同一台电脑打开[注册页](http://127.0.0.1:5173/register)，填写新用户名、尚未注册的收件邮箱和密码。打开验证邮件中的链接，输入注册时的密码完成验证，再用用户名登录。新账号有独立论文库，需要自己上传测试 PDF。若收不到邮件，先检查垃圾箱和 `./scripts/local-research logs mail`。[账号接口](../docs/api-contract.md#2-账号与会话)

<a id="已启动预览时直接从网页提交"></a>

## 本机一键启动

在 macOS 上启动 Docker Desktop，完成上面的首次配置。后端使用 `backend/.env` 指定的数据库与 `STORAGE_ROOT`。默认网页地址为 `http://127.0.0.1:5173`。在仓库根目录运行：

```sh
./scripts/local-research up
```

入口会启动 Compose 数据库、主 API、只读论文库、解析 Worker、研究 Worker 和前端。留空 `AGENT_LIBRARY_PUBLIC_URL` 时，它用 Docker Desktop 创建指向只读论文库的 Cloudflare 临时隧道。配置 arXiv 或 SMTP 后，对应的导入或邮件 Worker 也会启动。等启动器打印以「网页」开头、同时列出网页和论文库地址的一行，即可打开网页。此时数据库、前端代理和论文库公网健康检查均已通过。保持终端打开，作业回传后可按 Ctrl+C 停止本次进程。

同一份仓库重复运行 `up` 时，第二个终端会提示已有启动器。正常按 Ctrl+C 会关闭临时隧道，下次启动会生成新地址。如果异常退出只留下隧道容器，启动器会核对容器配置并通过公网健康检查复用原地址；原隧道不可用时会自动重建。

在[论文库](http://127.0.0.1:5173/papers)上传测试 PDF，从[新建研究](http://127.0.0.1:5173/tasks/new)提交问题。结果页地址最后一段是任务 UUID。另开终端在仓库根目录查询：

```sh
./scripts/local-research jobs            # 最近十条，含状态和 TACC 作业号
./scripts/local-research jobs TASK_UUID  # 只看这次任务
```

### 看终端日志

`up` 所在的终端会实时显示各服务的输出，每行开头的标签表示来源：

| 标签 | 看什么 |
| --- | --- |
| `[web]`、`[api]` | 前端开发服务、网页登录和研究请求。`POST /api/v1/agent-research` 返回 202 表示后端已受理。 |
| `[worker]` | 研究 Worker 的派发、重试或回传异常。查询某一单的状态和作业号用上面的 `jobs TASK_UUID`。 |
| `[library]`、`[parser]` | TACC 对只读论文库的 HTTP 请求、本机 PDF 解析进程的输出。 |
| `[imports]`、`[mail]` | 启用对应功能后，查看 arXiv 导入或邮件 Worker 的输出。 |

日志同时写入 `backend/runtime/local-research/<服务名>.log`，每次启动该服务会重写对应文件。需要单独跟踪时，另开终端运行 `./scripts/local-research logs worker`，或运行 `./scripts/local-research logs` 查看全部服务。两条命令都会先显示最近 20 行，再跟踪新输出。在这个查看窗口按 Ctrl+C 只退出日志查看。

### 单独启动进程

需要逐项调试时，在 `backend/` 运行 `uv run --locked uvicorn app.main:create_library_app --factory --host 127.0.0.1 --port 8001`，另开终端运行 `cloudflared tunnel --url http://127.0.0.1:8001`。将输出的 HTTPS 地址填入 `AGENT_LIBRARY_PUBLIC_URL`，按[后端启动说明](../backend/README.md#1-首次启动)分别启动主 API 和所需 Worker，再按[前端说明](../frontend/README.md#本地开发)启动网页。

## 从网页验证

打开 [本机网页](http://127.0.0.1:5173)，登录后在「论文库」上传一份 PDF。在「新建研究」先留空论文选择，按标题提问，并要求引用指定页的一项细节。得到答案后，点击正文引用，再点「查看 PDF 对应页」，核对论文、原文和页码。勾选同一篇论文再提交一次，可验证预选路径。任务内容由网页生成；[独立 Agent 的示例题](../agent/examples/library-qa.json)也可作为提问参考。

复现本次验收可上传[两页测试 PDF](<../frontend/checks/fixtures/Orchid Calibration Report.pdf>)，提问「只查我的论文库，《Orchid Calibration Report》最终校准记录的校验标签是什么？请引用第二页原文。」页面应给出 `LUMEN-472`，引用应能打开第二页。[浏览器验收脚本](../frontend/checks/live-tcloud.cjs)

每次提交仅同步两种模式所需源码、作业启动文件、任务清单和短期凭据。`input.zip` 只含 `manifest.json`、`task.json`、`sources.json`。预选论文随清单携带 UUID 与 SHA-256，动态检索按提交用户授权。两种路径都在作业首次读取时下载 PDF、核对摘要，沿用 Agent 的分页解析，无需向 `agent/data/` 复制文件。[Agent 读库实现](../agent/apis/library.py)

## 阶段二网页验收

在「新建研究 → 研究设置」选择 **Baseline** 或 **Extension**，默认 Baseline。两种模式在网页上默认使用 compact 上下文，可切换为 full。初次选择 Extension 时默认勾选 Planner 和 Reflection，可分别取消。预算随任务冻结，服务端上限由 `backend/.env` 中的 `AGENT_MAX_STEPS`、`AGENT_TIMEOUT_SECONDS`、`AGENT_CONTEXT_TOKENS`、`AGENT_OUTPUT_TOKENS` 和 `AGENT_SEARCH_MAX_PAPERS` 控制。

| 状态 | 用例 | 在网页中核对 |
| --- | --- | --- |
| 已有真实作业 | Baseline 库内搜索、预选、分页阅读、分块摘要 | 作业 30395、30387 和 30628，见下方记录。 |
| 已接入，待真实作业 | Baseline，开启搜索，参考论文留空，搜索一篇库里还没有的论文 | 「运行记录」有 `search_papers`，再看打开原文和阅读工具。在正文点击引用，导入同一 arXiv 版本，打开引用页。 |
| 已接入，待真实作业 | Extension，勾选两篇 PDF，开启 Planner、Reflection 和 compact，要求分别检索单篇及两篇并比较 | 核对 `planner`、`retrieve`、`embedding`、`retrieval_index` 和自然交稿后的 `reflection`；两篇分别有可点击的证据。进入上下文压力收尾时可跳过 Reflection。 |
| 两种模式的 Neon 写入与读回已实测，待真实作业 | 开启 `AGENT_PERSIST=true` 后运行两种模式 | 「运行记录」显示 Agent 数据库保存状态。网页仍从本机后端取结果，Worker 另外把解析文档和完整 TaskResult 写入配置的 Agent 数据库。 |

**Baseline 可复制问题**（先确认自己的库里还没有 LoRA）

```text
请用外部 arXiv 搜索找到 Hu 等人的 LoRA 原论文。根据原文解释训练时哪些参数被冻结、哪些参数被更新。给出引用和页码，以便我导入论文后打开对应页。
```

**Extension 可复制问题**（先上传并勾选 LoRA 与 QLoRA）

```text
请先在 LoRA 单篇中检索低秩更新公式，再在 LoRA 和 QLoRA 两篇原文中一起检索节省显存的机制。用表格比较冻结权重、训练参数和量化方式，每一行都给出两篇各自的页码证据。不要直接比较不同实验配置的显存数字。
```

Neon 使用 `agt_baseline.papers` 和 `agt_baseline.runs`。Baseline 的 run 键是网页任务 UUID，Extension 用 `extension/<网页任务 UUID>`。同一任务重交付按键更新。外部写入失败或解析文档超出交付上限时，网页保留研究结果并显示持久化失败。修改私有配置表后运行 `./scripts/local-research configure`，再重启本机服务。

## 查看作业

`GET /api/v1/tasks/{task_id}` 中的 `agent.remote_job_id` 对应平台作业号，`agent.dispatch_id` 对应持久目录。可隔几分钟运行 `tcloud ps -j JOBID` 看队列。作业开始后会写 `status.json`，其中 `state=running` 表示执行中，`succeeded` 或 `failed` 表示已结束。队列为空时，以状态文件和网页结果为准。留足从 Worker 领取到作业结束的时间，含排队和首次环境安装。

```sh
tcloud cat slurm_log/acs-DISPATCH_ID-JOBID.log
tcloud download acs-research/jobs/DISPATCH_ID/status.json ./status.json
tcloud download acs-research/jobs/DISPATCH_ID/result.json ./result.json
```

### 2026-11-22 手动网页提交

预选一篇《SkillOpt》并提交“总结这篇论文”。网页任务 `f55876b8-3a36-4dd4-ae26-cd20786943fe`，派发 UUID `6bfaf09e-fdad-40cb-b2d7-404c12dd959d`，TACC CPU 作业 `30628`。从提交到结果入库共 217 秒，其中 Baseline 执行约 129 秒。百炼模型调用 20 次，工具调用 9 次，覆盖打开原文、分块摘要和分页阅读。

后端状态为 `succeeded`，Agent 返回 `partial` 并列出附录和超参数的证据缺口。抽查正文中的两处结果与上传原件第 9、10 页一致。单篇总结额外生成了比较表，表中各项缺少引用，留待后续核对。此次轨迹没有调用外部搜索。Orchid 空预选和预选的自动化验收见下节，同题手动对照仍待复验。

### 2026-11-21 百炼验收结果

两次真实网页提交均由 Worker 自动派发到 TACC 并取回结果。两条任务都回答 `LUMEN-472`，点击引用打开了上传原件的第 2 页，下载文件的 SHA-256 与上传时一致。

| 网页提交 | TACC 作业 | Agent 实际调用的工具 | 百炼调用 |
| --- | --- | --- | --- |
| [预选一篇](http://127.0.0.1:19483/tasks/f2674517-7767-4fb8-a349-4ea86995bbdc) | `30387` | `open_paper` → `read_paper` | 3 次 |
| [空预选](http://127.0.0.1:19483/tasks/45333d05-2178-4241-86f6-e00936cdfa10) | `30395` | `search_library` → `open_paper` → `read_paper` | 4 次 |

SDK 提交需要同步源码和准备环境。首次尝试曾在 30 秒时超时；将提交等待单独设为 180 秒后，空预选作业成功完成。可用下列命令复核该作业的最终状态：

```sh
tcloud cat acs-research/jobs/1c323c36-1ff7-4ddd-8f96-d2a11d7e3fb7/status.json
```

更早的 CPU 作业 `30379` 已单独验证自动授权、按用户搜索、下载原文和跨账户隔离。[只读探测脚本](library-probe/submit.sh) · [课程 GPU 模型服务单独运行说明](qwen27b-student-release/README.md)
