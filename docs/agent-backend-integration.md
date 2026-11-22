# 后端与独立 Agent 对接

网页提交问题和可选论文，后端冻结输入、预算与用户权限。课程环境中，每个新任务对应一个 TACC CPU 作业，运行选定的 Baseline 或 Extension，通过 HTTPS 读取论文库并调用百炼。Worker 将结果写回数据库，网页从引用跳转到原 PDF。[从头启动与真实验收](../tacc/TACC.md) · [后端传输配置](../backend/README.md#8-独立-agent-配置)

## 从提交到作业

1. 登录用户调用 `POST /api/v1/agent-research`，提交 `question`、`paper_ids`、`allow_search` 和可选的 `research`。开启搜索可留空论文，关闭搜索至少选一篇。后端检查选中文件的归属，以 `202` 返回 `task_id`。同一请求重试时复用 `Idempotency-Key`。[统一研究接口](api-contract.md#13-v3-统一研究接口2026-11-20)
2. 每个任务绑定一个 `dispatch_id`。研究 Worker 领取后，在 `AGENT_EXCHANGE_ROOT/outbox/<dispatch_id>/` 生成 `input.zip` 和作业私有的 `library-access.json`。课程 ZIP 仅含 `manifest.json`、`task.json`、`sources.json`。每篇预选论文以 `local:<论文 UUID>@<SHA-256>` 标识，空预选时来源列表为 `[]`。[输入契约](../backend/src/app/agent_bridge/contracts.py)
3. Worker 用 `tcloud submit` 同步本次所需的 Agent 源码、作业脚本、输入和凭据。计算节点运行 `job.sh`，由 `run_job.py` 按清单调用 Baseline 或 Extension，启用 Agent 持久化时随结果回传解析文档。Python 3.12 和依赖可跨作业缓存。[提交文件清单](../backend/src/app/agent_bridge/tcloud.py) · [作业入口](../tacc/research/run_job.py)

## PDF 与权限

上传一次，PDF 原件保存在后端。预选时，Agent 按来源 ID 直接下载。未预选时，可用 `search_library` 搜索当前账号的论文，再下载命中的原件。Agent 在首次打开时核对 SHA-256，并按 PDF 物理页提取证据。`agent/data/` 无需预置用户论文。[Agent 论文库客户端](../agent/apis/library.py)

| 使用方 | 授权与范围 |
| --- | --- |
| 网页 | 使用登录 Cookie 和 CSRF 令牌创建任务。前端来源由 `FRONTEND_PUBLIC_URL` 指定。 |
| TACC 作业读取论文 | Worker 签发绑定本次派发的只读 Bearer 令牌。开启搜索时可列出、读取提交用户的论文。关闭搜索时列表返回 403，仅可下载预选原件。任务到期或进入终态后令牌失效。 |
| TACC 作业调用模型 | Worker 用私有 `AGENT_TCLOUD_MODEL_ENV_FILE` 中的百炼凭据换取本次作业的临时 key。有效期取任务剩余时间，最长 30 分钟。 |

`AGENT_LIBRARY_PUBLIC_URL` 填计算节点可访问的 HTTPS 地址。采用临时隧道时，将它指向本机 `app.main:create_library_app`（示例端口 `8001`）。该入口只提供 `GET /health`、`GET /api/v1/agent/papers`、`GET /api/v1/agent/papers/{paper_id}/pdf` 和作业专用的 `GET /api/v1/agent/search-arxiv`。网页登录与任务提交使用主 API（示例端口 `8000`）。独立调试可从主 API 的 `POST /api/v1/agent/library-token` 申请会话令牌。[论文库 API](api-contract.md#41-agent-论文库)

搜索代理只接受开启搜索的活动作业令牌，查询域固定为 arXiv。Tavily key 和 Agent 数据库连接串保留在本机；聊天和嵌入使用百炼短期凭据。

## 结果与恢复

作业在 `$TACC_USERDIR/acs-research/jobs/<dispatch_id>/` 原子发布 `status.json` 和 `result.json`。状态遵循 `agent-job-status-v1`。结果信封遵循 `agent-result-v1`，包含 `dispatch_id`、`input_sha256`（ZIP 内 `manifest.json` 原始字节的 SHA-256）、`remote_job_id` 与完整 Agent `result`。[结果契约](../backend/src/app/agent_bridge/contracts.py)

Worker 查询队列并下载结果，核对作业号、任务、清单摘要和引用。库内检索到的论文还要校验所有者、文件摘要及引用页码，随后保存任务关联。预选与检索所得在数据库中分别记录。网页展示的引用可定位原 PDF 页，原生结果保留 Agent 的来源标识、trace、用量及未解决项。[结果校验与入库](../backend/src/app/agent_bridge/store.py)

| 查询 | 用途 |
| --- | --- |
| `GET /api/v1/agent-research/{task_id}` | 网页研究详情、正文与引用。 |
| `GET /api/v1/tasks/{task_id}` | `agent.dispatch_id`、平台作业号 `agent.remote_job_id`、限额和停止原因。 |
| `GET /api/v1/tasks/{task_id}/agent-result` | 原生结果及对应的派发信息，尚未收到时 `result=null`。 |

任务期限从 Worker 首次领取开始，包含打包、排队和执行。重启后 Worker 继续跟踪原派发。SDK 提交默认最多等待 180 秒（`AGENT_TCLOUD_SUBMIT_TIMEOUT_SECONDS`），普通查询默认 30 秒（`AGENT_TRANSPORT_TIMEOUT_SECONDS`）。

提交回执不明时，Worker 保留记录并用同一派发的远端状态恢复作业号。作业离开队列后，后端校验并保存结果才算交付。`completed` 和 `partial` 都可展示正文，`partial` 同时展示未解决项。[Worker 实现](../backend/src/app/agent_bridge/worker.py) · [查询作业的命令](../tacc/TACC.md#查看作业)

## 兼容传输

`manual`、`local` 和历史 SSH/Slurm 的 `tacc` 共用清单与结果格式，其 ZIP 另含预选原件 `papers/<UUID>.pdf`。手动执行端将完整信封原子写入 `inbox/<dispatch_id>/result.json`。本地进程模式依赖单独部署的兼容 `run_dispatch.py`，SSH 模式依赖远端已部署的 helper 和 Slurm 环境。课程 `tcloud` 使用仓库自带的作业入口。旧客户端通过 `POST /api/v1/tasks` 提交的摘要、问答和综述仍使用固定来源。[本地与手动适配器](../backend/src/app/agent_bridge/transport.py) · [SSH 适配器](../backend/src/app/agent_bridge/tacc.py)
