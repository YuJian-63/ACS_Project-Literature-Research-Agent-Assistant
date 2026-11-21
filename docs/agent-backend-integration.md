> **当前 v3 分支说明（2026-11-21）**：本分支保留独立数据库 `literature_v3`（55435）、存储 `runtime/v3/storage`、Cookie `lra_v3_session`，前端 5175、API 8002。迁移入口仍是 `alembic_v3`，新增 `v3_0002`；不得按下文历史环境配置切回 v2。统一研究使用 `/api/v1/agent-research`；Task/AgentRun 是执行内部依赖，旧三类任务路由未挂载。启动和合并限制见 [v3 合并说明](v3-main-merge-resolution.md)。下文保留 main 的历史说明及技术细节，与本段不符的部署参数以本段为准。

# 后端与独立 Agent 对接

更新：2026-11-20。本文件描述后端适配、Agent 本地 PDF、独立作业入口及第 3.1–3.3 阶段本地/TACC 传输、恢复和清理。离线测试与真实集群验收分开记录；真实 TACC 部署和模型验收由操作者统一执行。

V3 增量：`/api/v1/agent-research` 复用本文的派发和结果路径，无需新增迁移。支持 0—20 篇已选 PDF，允许只提问、由 Agent 自主检索；allow_search=false 时仍要求指定论文。详细请求/响应、服务端预算及会话变化见 [API 第 13 节](api-contract.md#13-v3-统一研究接口2026-11-20)。旧 `/tasks` 保持指定来源且关闭搜索的契约。

V3 外部来源阅读：Agent 原生结果继续保留 arXiv 标识和明确版本，不伪造本地 UUID。前端让用户确认导入该版本，待后端下载及解析完成后再进入本地 PDF 阅读器，并保留原引用页码与返回研究位置。仅 Agent 可搜索仍不足以完成导入；后端须配置 arXiv 并运行 Import/Parser Worker。无明确版本的来源提示先确认版本，不自动下载最新版本。

## 1. 本轮边界

新增 `TASK_RUNNER=agent`。该模式在任务创建阶段即分流，不调用后端的关键词扩展、PaperChunk 检索、单篇生成、分阶段综述或旧证据校验。账号验证、用户归属、并发配额、幂等提交、任务状态、租约及原始 PDF 继续由后端管理。

`mock` 和 `langgraph` 保留兼容已有部署与历史任务。新模式不会在 Agent 失败时回退到旧实现。后端不导入 Agent 运行环境，因此后端 Python 3.11+ 与 Agent Python 3.12 可以独立部署。

文件交换协议继续作为边界。AGENT_TRANSPORT 可选 manual（兼容外部文件交换）、local（独立进程）和 tacc（SSH/Slurm）。TACC 适配器通过已验证主机密钥的 OpenSSH 调用受控远程桥接；不会解析旧 tcloud CLI 面向人工的查询输出。完成部署配置前保持 AGENT_DISPATCH_ENABLED=false，不能将代码实现视为集群已经验收。

## 2. 数据流

1. 登录用户提交原有 `POST /api/v1/tasks`。后端检查所有论文归属，绑定 PDF 的 SHA-256，生成一次性的 `dispatch_id`。客户端 budget 不参与策略或幂等请求摘要。
2. 后端在同一事务保存 Task、TaskPaper、首条事件和 AgentRun。Agent 模式接受 uploaded/processing/ready 原始论文，不要求旧解析片段。failed 论文仍需先处理上传/解析错误。
3. `app.runner_worker` 按 TASK_RUNNER 路由到独立 AgentWorker。Worker 对领取的任务维持租约，原子发布输入 ZIP。
4. 选定适配器上传 ZIP 到 dispatch 专属目录，提交或恢复同一作业，查询执行状态，下载完整结果信封。local 由监督进程调用独立 Agent 环境；tacc 由远程桥接调用 sbatch。路径和平台密钥不进入模型输入。
5. 后端接收对应 dispatch 的原子结果文件，验证格式、任务和输入身份、来源归属与页码边界，在事务内保存原生结果并生成兼容页面的展示记录。
6. 页面继续用原本的任务/事件/结果接口；新增原生结果查询可读取 Agent 的 trace、errors、configuration、usage 和 unresolved。

现有论文库 Parser 可作为旧部署和页面元数据能力保留，但 Agent 任务不使用它的片段开展研究。Agent 解析元数据回填论文库和前端进一步展示原生状态可在后续对接阶段完善。

## 3. 输入文件

默认交换目录位于 `STORAGE_ROOT/agent-exchange`，不对浏览器提供目录下载：

```text
agent-exchange/
  outbox/<dispatch_id>/input.zip
  inbox/<dispatch_id>/result.json
```

ZIP 内仅包含明确选中的文件：

```text
manifest.json
task.json
sources.json
papers/<paper_uuid>.pdf
```

没有压缩整个仓库，也不包含 .env、用户凭据或其他论文。打包时重新计算原始文件大小和 SHA-256；改变了的文件不会发布。完成前仅生成 .part 文件；`input.zip` 的出现才表示包完整。重复处理同一 dispatch 复用同一输入。

`manifest.json` 结构：

```json
{
  "schema_version": "agent-dispatch-v1",
  "dispatch_id": "<uuid>",
  "task": {
    "task_id": "<backend task uuid>",
    "question": "<task instructions and original user question>",
    "sources": ["local:<paper_uuid>@<sha256>"],
    "allow_search": false,
    "max_papers": 1,
    "max_steps": 20,
    "timeout_seconds": 360.0,
    "max_output_tokens": 4096
  },
  "sources": [{
    "source_id": "local:<paper_uuid>@<sha256>",
    "paper_id": "<paper_uuid>",
    "title": "<paper title>",
    "path": "papers/<paper_uuid>.pdf",
    "sha256": "<64 lower-case hex characters>",
    "size_bytes": 12345,
    "page_count": null
  }],
  "runtime": {"context_window": 32000, "persist": false}
}
```

`task.json` 就是 manifest.task，严格沿用 `agent/schemas.py`；task_type 已转换为 question 的任务说明，不增加旧 budget 或 attachments 字段。`sources.json` 是 manifest.sources。runtime 是调用 `run_task` 的关键字参数，不属于 Task；远程包装器必须显式使用 `persist=False`。

**第 1 阶段已实现**：Agent 的 `apis/pdf.py` 提供通用原文解析；`apis/sources.py` 的 `SourceReader.from_manifest(input_root)` 按 sources.json 读取指定 PDF，校验来源身份、相对路径、大小、完整 SHA-256 及可选页数。baseline 支持 `local:` 输入、工具调用、原文和摘要引用，也保留 arXiv 行为。Python 使用 `run_task(task, reader=reader, persist=False, context_window=...)`；本地 CLI 使用 `--input-root`。见 [授权本地 PDF](../agent/README.md#授权本地-pdf)；独立 Agent 的通用接口文档保持 main 版本，部署协议以本文及 `agent/agent_io/` 为准。

本地引用返回后端论文 UUID、完整 local source_id、物理页号和逐字原文块，`version=null`、`url=""`；不向模型暴露文件路径。缓存命中仍核验文件。第 2 阶段由 `agent/run_dispatch.py` 实现 ZIP 校验、安全展开、独立执行和结果信封，见第 8 节；第 3 阶段适配器只传输该信封，不能投递普通 baseline CLI 的结果文件。

## 4. 结果信封

远程包装器保存完整 `TaskResult.model_dump(mode="json")`，而非 CLI 标准输出摘要，再由传输桥接交付：

```json
{
  "schema_version": "agent-result-v1",
  "dispatch_id": "<same dispatch uuid>",
  "input_sha256": "<SHA-256 of canonical manifest JSON>",
  "remote_job_id": "<platform job id or null>",
  "result": {
    "task_id": "<same backend task uuid>",
    "question": "<exact manifest.task.question>",
    "answer": "<Agent Markdown>",
    "comparison_table": "<Agent Markdown table or empty string>",
    "citations": [],
    "unresolved": [],
    "stop_reason": "completed",
    "usage": {"agent_steps": 1, "model_calls": 1, "tool_calls": 0, "input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "token_usage_complete": true, "elapsed_seconds": 1},
    "sources": [], "trace": [], "errors": [], "configuration": {}
  }
}
```

示例仅说明字段结构，不代表合格研究证据。真实引用必须由 Agent 获取和校验。

规范 JSON 算法为 Python `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")`。清单通过后端 contracts 模型规范化后写入 ZIP；对包中 manifest.json 的原始字节计算 SHA-256 即可，不应重新序列化改变 360.0 等数字形式。

结果先写到同一 inbox 目录下的临时文件，再原子重命名为 `result.json`；后端不会等待修复一个已发布的损坏 JSON。默认最大 16 MiB。未知版本、重复 JSON 键、非有限数、任务不匹配、其他 dispatch 或输入摘要、越权来源和非法页码均拒绝。结果目录只应由受信任的本地传输桥接写入，输入摘要用于关联，不能代替身份认证。

本地引用的 source_id 必须等于清单里的 source_id；paper_id 可为该 source_id 或后端 paper UUID。Agent 的不透明 chunk_id 原样保存；旧产物视图仅把本地引用映射为 C1/C2，原始 Agent 结果不修改。页码指原始 PDF 的物理页，不能使用重新排版后的 PDF。后端不再执行旧逐字片段内容或检索相关性算法。

V3 开启 allow_search 后，额外来源仅接受规范的 arXiv 标识：版本化或带 PDF 哈希前缀的 source_id、匹配的 paper_id、canonical abs URL，以及相同来源/页号的 chunk_id。外部引用必须在 result.sources 中登记；所选加检索论文总数不能超过 task.max_papers。外部证据保留在 AgentRun 原生 JSON 中，不创建虚假的本地 Paper/Citation 外键。本地越权、外链伪造、重复和空引用检查仍生效。

仅搜索的 ZIP 只有 manifest.json、task.json、sources.json 三个成员，sources 为 []；混合来源继续携带授权 PDF。清单仍绑定 task.sources 和 PDF SHA-256；不得因为允许外部搜索就允许读取其他本地文件。后端和 local/TACC 上的 Agent 包装器必须一起升级；Agent 研究核心不变。

completed 和 partial 保存可阅读 artifact；partial 的 task.stage 为 partial，保留停止原因与 unresolved，并写入 warning 事件。其他 stop_reason 写入明确的 `AGENT_<STOP_REASON>` 错误，不创建成功 artifact，但原生结果仍可查询。已失去租约、超时或已终结的任务不会被迟到结果覆盖。

## 5. 动态限制和恢复语义

选中 N 篇论文时，服务器计算：

- max_steps = min(AGENT_MAX_STEPS, 16 + 4N)。它只限制 Agent 主循环，不代表所有摘要内部调用次数。
- timeout_seconds = min(AGENT_TIMEOUT_SECONDS, 300 + 60N)。从本地 Worker 首次领取开始，包含打包、传输与等待。
- max_output_tokens = min(AGENT_OUTPUT_TOKENS, AGENT_CONTEXT_TOKENS - 2048, 4096 + 768(N - 1))。这是每次模型输出上限，不能保证长综述永不截断。
- context_window = AGENT_CONTEXT_TOKENS。Agent 仍负责真实上下文容量检查，2048 仅是本策略为输入留出的最小空间。

没有声称 Agent 已提供累计 Token 硬预算。旧接口和数据库中的 `budget.max_tokens=100000` 是兼容字段，Agent 模式不发送或执行这个总量限制；调用方以 task.agent.limits 为准，真实 Token 用量从 TaskResult 读取，未知值保持 null。

每个 Task 只有一个持久化 dispatch。Worker 租约过期后重新领取同一任务，保留首次 started_at 和截止时间。多个 Worker 可领取不同任务，单个 Worker 顺序执行。local 保存不可重复的提交凭据，重启不重新启动同一目录；TACC 保存提交 claim 与回执，响应不明时按完整作业名核对 squeue/sacct，仅恢复唯一匹配，不盲目重提。remote_job_id 在受租约约束的事务内保存，后续状态/结果必须匹配。不能据此承诺平台 exactly-once。

网络/调度暂时不可用时有界退避重试，仍受原任务截止时间约束。任务失败或超时后，维护循环核实并取消未交付作业；Worker 重启后补偿处理。停止 Worker 不等于取消运行中的任务。local 监督进程另有执行超时，TACC 同时设置 Slurm walltime；取消请求与确认均不新增业务状态。增量模型事件尚未实现。交换包可能含用户论文，默认保留七天且不自动删除；维护命令默认 dry run，显式 --cleanup --apply 才清理已终态且超过保留期的受控目录。清理保留无论文内容的 dispatch 摘要凭据，防止旧任务被重新提交。原 reset_data 不负责这些目录。

## 6. 新增查询接口

全部沿用登录会话和任务所有者检查：

- `GET /api/v1/tasks/{id}`：增加可空 agent，包括 dispatch_id、transport、remote_job_id、stop_reason、unresolved 和 limits。
- `GET /api/v1/tasks/{id}/agent-result`：返回 task_id、dispatch_id、input_sha256、status、remote_job_id、result。尚未接收结果时 result=null；不是 Agent 任务返回 404。失败任务也可以读取已接收的原生结果。
- `GET /api/v1/tasks/{id}/artifacts`：Agent 模式把 answer 与 Markdown comparison_table 合并到 content_markdown；旧结构化 comparison_table=null，另附 comparison_markdown、agent_stop_reason、unresolved。正文与 comparison_markdown 使用同一组已保存引用映射为 C1/C2，原生结果不变。前端提供 Markdown 比较标签及表内引用；保留旧结构化表格兼容。
- 引用响应的 chunk_id 扩为 UUID 或原生字符串，另有可空 agent_source_id；paper_id 仍为后端原始论文 UUID，本地阅读跳转保持有效。
- `GET /api/v1/tasks?is_mock=false` 同时包含 langgraph 和 agent 任务。

部分交付的任务仍为 succeeded，但 stage/stop_reason 为 partial；页面和历史显示“部分完成”，详情展示 unresolved，不误报完整研究已完成。local/TACC 失败任务尚无结果且未确认作业停止时，删除返回 `409 AGENT_STOP_PENDING`，避免丢失取消所需的持久化记录。维护循环确认停止后允许删除；已交付终态结果按原规则删除。

新任务按用户提问的主要自然语言回答，与界面和论文语言无关；中文问题中的英文术语不改变回答语言。摘要未填写关注点时默认中文，引文保留原文。后端将此规则写入派发指令，不增加客户端语言参数，不改写既有 manifest 或历史结果。

## 7. 启用前准备

合并 main 后，唯一迁移 head 为 `20261120_0007`。main 的 `20261118_0006` 保持导入来源元数据迁移；Agent 扩展后移到 `20261120_0007`，新增 agent_runs，扩充 tasks 的 runner 枚举与恢复约束，允许 citations 保存原生 Agent 引用而不引用旧 paper_chunks。若历史 backend-dev-v2 数据库已将 Agent 扩展记为 `20261118_0006`，升级会识别已存在的 Agent 表并补齐缺失的 source_metadata，不重建任务表或清库。存在 Agent 数据时仍拒绝直接 downgrade。部署前执行 `alembic upgrade head` 和 `alembic check`，不要手工 stamp 或删表。

本轮不自动修改实际 .env 或用户数据库。由用户按操作文档完成部署、迁移并选择传输后启用；下列为共用参数，完整 local/tacc 配置见第 9 节：

```dotenv
TASK_RUNNER=agent
AGENT_DISPATCH_ENABLED=true
AGENT_EXCHANGE_ROOT=
AGENT_MAX_STEPS=100
AGENT_TIMEOUT_SECONDS=1800
AGENT_OUTPUT_TOKENS=8192
AGENT_CONTEXT_TOKENS=32000
AGENT_RESULT_MAX_BYTES=16777216
AGENT_POLL_SECONDS=2
```

模型和 TACC 平台凭据仅在远程环境或受信任的传输桥接配置，不能写进输入包。此模式不使用本地 LLM_* 配置。


## 8. 第 2 阶段：独立作业入口

`agent/agent_io/` 不导入后端包，`agent/run_dispatch.py` 是后续平台作业应调用的入口。它从可信调用参数校验 dispatch UUID 与 manifest 原始字节摘要，要求 task/sources/runtime 严格一致，安全展开到本次临时目录后执行现有 Agent。执行显式使用 `persist=False`，模型配置来自 Agent 运行环境，不包含在输入 ZIP 中。

入口验证 ZIP 成员、文件大小、PDF 摘要及结果的任务身份、来源、页号和可持久化字段。result.json 以完整 `agent-result-v1` 信封原子发布，默认上限 16 MiB；后端仍独立校验收到的信封。输入包、结果和工作根目录均须由可信操作者管理。临时目录退出时清理，持久化输出保留结果与脱敏状态。

独占锁避免同一输出目录同时运行；有效已完成结果（包括完整研究失败结果）会复用，包装器失败且没有结果、运行中或崩溃状态不会静默重跑。按第一种简化方案保留 status.json，state 统一为 running/succeeded/failed：completed/partial 对应 succeeded，其余研究停止原因或包装器异常对应 failed，原始 stop_reason 与 unresolved 保留作详情。后端仍使用 queued/running/succeeded/failed；只有结果通过校验并持久化后才进入后端终态。旧 finished 仅兼容读取，验证结果后修正，新执行不再写入。包装器失败不伪造研究结果，只记录安全错误代码和类型。协议、退出码与恢复语义见 [作业接口](../agent/agent-io-interface-v1.md#42-后端输入包与作业入口)，Windows/macOS 命令见 [操作手册](terminal-operations.md#agent-第-2-阶段远程作业入口)。

已用后端真实 export_bundle、Agent 原始 PDF 阅读与脚本模型、后端 read_result/validate_delivery/present_result 完成跨独立 Python 环境的离线往返验证，包括原文物理页和 C1 展示映射。该验证没有使用真实模型、业务库或 TACC，也不代表已在 macOS 运行。

## 9. 第 3.1–3.3 阶段：传输、调度和恢复

### 本地闭环

AGENT_TRANSPORT=local 需要 AGENT_LOCAL_ROOT 与 AGENT_LOCAL_PYTHON；相对路径从 backend/ 解析。适配器不导入 Agent 包，而是启动后端监督进程，再由指定的 Agent Python 执行 run_dispatch.py。提交、退出与取消请求保存在交换根目录 jobs/<dispatch_id>/。进程标准输出不作为研究结果，不收集可能含模型内容的原始 stderr。

同一输入重复上传必须一致；提交 marker 先落盘，再启动进程。监督进程脱离 Worker 生命周期，写原子 exit.json，并响应 cancel.request。崩溃遗留的提交 marker 不会自动触发新模型作业。Worker 恢复会读取同一 dispatch，仍受原截止时间控制。本地 submission.json 保存首次 started_at 推导的绝对 deadline；监督进程在启动前检查，过期不启动 Agent，重启和重复提交均不延长截止时间。

### TACC 闭环

AGENT_TRANSPORT=tacc 需要 AGENT_TACC_HOST（OpenSSH 别名）、AGENT_TACC_HELPER、AGENT_TACC_CONFIG（远程绝对路径）。SSH 使用 BatchMode=yes 和 StrictHostKeyChecking=yes，不传密码、不关闭主机校验。后端无需安装 tcloud 或共享 Agent 虚拟环境。远程登录节点需 Python 3.11+、sbatch、squeue、sacct、scancel；AGENT_TACC_PYTHON 默认为 python3，也可指定远程 Agent 的 3.12 解释器。Agent 目录、Python 环境、模型配置与工作根目录须同时对登录和计算节点可见。

远程 agent/tacc_bridge.py 只依赖标准库。请求通过 SSH stdin 传入；上传是一个有界 JSON 头加原始 ZIP 字节流。远程文件名由操作与 dispatch UUID 决定，不能请求任意路径。上传重新核对 manifest 摘要，Agent 再独立完整校验 ZIP、PDF 与来源。stdout 仅返回版本化、脱敏的 JSON。

作业名固定为 acs-<dispatch UUID 去掉连字符>。提交前保存 submitting.json；sbatch --parsable 返回的 ID 写 submission.json 后回传。提交中断时查询完整作业名及提交时间后的 accounting 记录，只有唯一匹配才恢复；零匹配表示不明确，多个匹配明确失败，均不再次 sbatch。Slurm 使用 --no-requeue 防止节点故障后自动重跑模型。若调度响应不明且 accounting 不可用，会保守等待至任务截止并尝试取消，需要操作者核查，不会假装“尚未提交”。

### 状态和错误

TACC 提交同样携带绝对 deadline；已经过期的任务不执行 sbatch。计算节点启动时再次检查期限，并以剩余秒数限制 Agent 子进程；即使平台排队延迟或后端离线，也不会重新获得完整执行时长。Slurm walltime 提供额外上限。数据库、本机和集群应同步系统时钟，明显时钟偏差会影响截止判断。

业务状态仍仅 queued/running/succeeded/failed。平台的排队/运行/终态留在传输层。Agent 的 status.json 只作状态证据；成功必须有完整结果并校验入库。失败研究保留原生结果及 stop_reason，包装器失败不伪造结果。Worker 同时校验状态与结果的停止原因，running 与结果刚发布之间的合法短暂窗口除外。旧 finished 兼容读取，不能代替结果。

| 错误码 | 含义 |
|---|---|
| AGENT_WRAPPER_FAILED | 包装器只返回安全错误码/异常类型，无完整结果 |
| AGENT_RESULT_MISSING | 终态缺少完整结果 |
| AGENT_PROCESS_FAILED / AGENT_LAUNCH_FAILED | 本地 Agent 异常退出或无法启动 |
| AGENT_PLATFORM_FAILED / AGENT_PLATFORM_TIMEOUT | Slurm 失败或超时 |
| AGENT_SUBMISSION_UNCERTAIN | 提交记录存在，但无法安全判断实际作业；禁止盲目重提 |
| AGENT_DUPLICATE_JOBS | 恢复找到多个同名作业，禁止猜测作业身份 |
| AGENT_DELIVERY_INVALID | 身份、大小、状态或产物校验失败 |
| AGENT_TRANSPORT_CHANGED | Worker 配置与任务提交时冻结的传输类型不同 |
| AGENT_DISPATCH_RETIRED | 该 dispatch 已按保留策略清理，禁止重新执行 |

### 部署与验收

完整 Windows/macOS 命令、部署包、安全配置、恢复、补偿取消、清理及统一验收矩阵见 [终端操作手册](terminal-operations.md) 末尾和 [统一验收清单](agent-transport-acceptance.md)。2026-11-20 合并 main 后以 `20261120_0007` 为唯一 head。

实现依据：TACC 官方 quickstart 与 tcloud-sdk 源码中的 SSH/Slurm 通道；Slurm 官方 sbatch、squeue、sacct、scancel 文档。远程 SSH 入口、共享路径、分区权限、accounting 可用性和模型连通性需在真实集群统一验收。

## 10. 原文阅读上下文管理

2026-11-20 合并后，以 main 的 `prepare_context` 和上下文压力收尾逻辑为准，不启用暂存中旧的 prepare_bounded_context、归档恢复或重复读取收尾策略。

默认保留完整历史。主循环准备上下文后，估算输入加输出预留达到 context_window 的 80% 且仍未超过硬上限时，进行一次无工具最终作答。trace 记录 `action=finalize`、`reason=context_pressure` 和 `purpose=finalize`；输出继续校验引用与原文。超过硬窗口仍停止为 context_limit，不进行压缩、裁剪或循环重试。

`context_finalize_ratio` 属于 Agent 运行参数，默认 0.8；后端不将它混入 Task JSON，也不修改已经持久化的 dispatch 清单及摘要。local/TACC 包装器继续调用 baseline.run_task，使用该默认策略。main 新增的 extension.py / retrieval.py / embeddings.py 保留原样；现有后端任务仅开放 baseline，暂未将 extension 工作流接入派发协议或前端入口。

该策略不保证任意篇幅都能在固定窗口内完成。分段摘要仍单独检查容量，不触发最终作答；达到步数或时间上限不会追加收尾。已发生的调用量、完整 trace 和未解决项均按 Agent 原生结果保留。

本次合并部署须先升级到 `20261120_0007`，再重启 API 和研究 Worker。已经终态的任务不会自动重跑。本地模式使用更新后的 Agent 文件，TACC 模式需重新打包部署 Agent。离线测试不代表真实模型或 TACC 已验收。

前端后续统一修改范围、已核对差异、待补后端契约及页面验收条件见 [前端 Agent 适配待办与统一修改方案](frontend-agent-adaptation.md)。该文档仅为待实施清单，不表示前端适配已完成。
