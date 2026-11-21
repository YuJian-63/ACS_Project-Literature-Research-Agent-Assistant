# 本地前后端与 TACC 作业

前端、FastAPI、PostgreSQL 和派发 Worker 在本地运行。本地向课程 TACC 提交作业入口和任务输入，集群排队调度，入口在计算节点调用 `run_task`。作业只在运行期间可以主动访问外部服务，整个流程无需与计算节点实时交互。

## TACC 参考资料

`tacc.zip` 解压到仓库根目录的 `tacc/`，与 `agent/` 同级。目录索引和常用 `tcloud` 命令见 [TACC README](tacc/README.md)。

- [Public 发布包](tacc/qwen27b-student-release/README.md) 提供课程环境中的模型服务和客户端示例。
- [Private vLLM 发布包](tacc/qwen27b-private-vllm-student-release/README.md) 提供修改 vLLM 源码后构建并启动服务的示例。构建所需的 `vllm-v0.26.0.tar.gz` 由 Git 忽略，重新检出后可从原始 `tacc.zip` 恢复。
- [API 探测](tacc/probe/README.md)、[测试后端](tacc/backend-probe/README.md) 和 [Tunnel 探测](tacc/tunnel-probe/README.md) 分别覆盖作业访问外部 API、测试 JSON/PDF 接口和通过隧道下载本机 PDF。

## 一次研究任务怎样运行

1. **前端提交。** 用户在研究页填写问题，可选论文并指定是否允许搜索。页面向本地 `POST /api/v1/agent-research` 发送问题、论文 UUID、搜索开关和幂等键。收到 HTTP 202 和 `task_id` 后打开结果页。[前端请求](frontend/src/api/agentResearch.ts)
2. **本地 API 入队。** 后端核对用户、论文归属和任务配额，在 PostgreSQL 记录任务、`dispatch_id`、输入清单和选定的传输方式。此时任务为 `queued`。[提交逻辑](backend/src/app/tasks/unified.py) · [入库逻辑](backend/src/app/agent_bridge/submission.py)
3. **本地 Worker 准备批作业。** 独立运行的 `python -m app.runner_worker` 领取任务，将参数、来源清单和预选 PDF 打成 `input.zip`。目标是通过课程平台支持的批作业入口提交任务，记录作业 ID。[Worker](backend/src/app/agent_bridge/worker.py)
4. **作业运行 Agent。** 排队结束后，作业脚本在计算节点启动 Python，读取输入包并调用 `baseline.run_task`。预选 PDF 从输入包读取；若要搜索用户论文库，由运行中的作业主动请求可达的后端。任务结束时，作业写出带任务标识的结果文件。
5. **本地展示结果。** 原 Agent 项目用 `tcloud download` 取回探测作业的文件；正式 Agent 需按派发协议交付完整结果。拿到结果后，现有后端可以校验并入库，更新任务终态。前端结果页在 `queued` 或 `running` 时每两秒查询一次本地 `GET /api/v1/agent-research/{task_id}`。[结果入库](backend/src/app/agent_bridge/store.py) · [前端轮询](frontend/src/features/agentResearch/ResultPage.tsx)

## 联调缺口

- **后端原方案。** 本地 Worker 通过非交互 SSH 调用登录节点的 helper，由 helper 用 `sbatch` 提交批作业。后续通过同一 helper 查状态、取消作业、取回结果。该方案要求课程账号允许非交互 SSH、自定义 helper 及 Slurm 命令，当前项目尚未验证这些权限。[现有适配器](backend/src/app/agent_bridge/tacc.py)
- **建议先验证的通道。** 原 Agent 项目已有 `tcloud submit`、`tcloud ps -j JOBID` 和 `tcloud download` 的探测记录。优先用独立作业目录跑一份预选 PDF：作业读取输入包，执行 `baseline.run_task`，把结果按作业保存到 `TACC_USERDIR`，本机下载后走现有结果校验。成功后把这组操作接入 Worker 的传输接口，核对同一 dispatch 在重启或提交响应丢失时不会重复提交。前端、任务表和结果页可沿用。
- **作业入口。** 当前分支已有 `baseline.run_task`；部署清单引用的 `run_dispatch.py`、`agent_io/`、`tacc_bridge.py` 和 `tacc.example.json` 缺失。联调先用平台支持的作业入口验证“读输入包 → 跑 Agent → 写结果”。[打包清单](backend/src/app/agent_bridge/deploy.py)
- **作业中访问论文库。** 预选 PDF 已随输入包上传。若 Agent 在运行中自主搜索库内论文，计算节点还需能访问本地后端的对外服务地址。计划由后端在提交时绑定用户和作业，作业开跑时凭专用凭据换取只读 token，并按需续取。原 Agent 项目的 CPU 作业 `29958` 已经由 HTTPS 隧道下载本机测试 PDF 并核对 SHA-256。正式论文库的签发接口依赖登录会话，令牌最长有效 30 分钟；作业凭据交换与续取待实现。
- **动态发现的库内引用。** 检索和下载函数已在本地用同一 Bearer token 验证，工具接入待完成。后端结果校验当前接受清单内的库内来源和按搜索规则发现的 arXiv 来源；还需校验作业中新发现的库内论文归属与 SHA-256，并映射到本地 PDF 页码。[结果校验](backend/src/app/agent_bridge/results.py)
