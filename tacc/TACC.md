# 研究任务如何在 TACC 上运行

用户登录网页并提交问题。目标是由服务器 Worker 向课程 TACC（Turing AI Cloud）派发 CPU 作业，Agent 通过 HTTPS 搜索该用户的论文库、下载 PDF，服务器取回答案和引用。先验证读库，再用百炼 API 跑完整研究流程，课程 GPU 模型服务单独验收后接入。

## 作业怎样获得论文库权限

在 Worker 设置 `AGENT_LIBRARY_PUBLIC_URL` 为计算节点可达的 HTTPS 后端地址。Worker 领取研究任务后，会在 `outbox/<dispatch_id>/input.zip` 旁写入私有的 `library-access.json`，内含地址和作业令牌。作业用该令牌调用两个论文库 GET 接口，用户只需登录网页提交任务。[Worker](../backend/src/app/agent_bridge/worker.py) · [Agent 客户端](../agent/apis/library.py)

后端根据派发记录检查任务所有者、搜索权限和截止时间。开启搜索时能检索及下载该用户的论文，关闭搜索时只能下载预选论文。任务终结或到期即失效。浏览器手动签发的会话令牌仍用于独立调试。[论文库接口](../docs/api-contract.md#41-agent-论文库)

## 每次提交什么

| 内容 | 首轮联调约定 |
| --- | --- |
| Agent 源码 | `tcloud submit` 同步当前提交目录，包括隐藏文件。首轮按 `dispatch_id` 建独立目录，仅放所需源码、`tuxiv.conf`、启动脚本、模型地址和 `input.zip`。同名目录重提可能覆盖远端工作区。 |
| 问题和论文 | 网页提交问题和可选的论文 UUID。首轮留空预选论文，沿用 `allow_search=true`，现有 `input.zip` 只含 `manifest.json`、`task.json` 和 `sources.json`。 |
| 模型与依赖 | 论文库探测仅需 CPU 和 PDF 读取依赖。完整 Agent 的下一轮联调用百炼 API，之后可切换到集群内的课程模型地址。 |

首轮源码随作业同步。后续可用 `tcloud upload` 将同一版本的 Agent 一次上传到 `TACC_USERDIR`，每次只提交入口、版本号、模型地址和输入包。`TACC_WORKDIR` 用于当次执行，`TACC_USERDIR` 用于持久保存和下载。[课程发布包](qwen27b-student-release/README.md) · [官方 tcloud Quickstart](https://github.com/turingaicloud/quickstart)

## 用户上传的 PDF 怎么读

用户在网页「论文库」上传一次 PDF，就可以勾选它发起研究，也可以让 Agent 自行检索。预选时，研究请求只传论文 UUID，后端将 UUID 和 SHA-256 写入任务。两条路径都可复用现有 `LibraryClient`。首次打开时下载原件到临时目录，校验 SHA-256，按原始页码解析，同一任务后续读取复用解析结果。[上传接口](../backend/src/app/api/papers.py) · [库内 PDF 读取](../agent/apis/library.py)

`agent/data/papers/` 是按 arXiv ID 查找的缓存，Agent 不会扫描其中的任意 PDF。如果今后需要离线附件，可沿用每个作业自己的 `papers/<UUID>.pdf`，按清单把来源映射到文件，再调用已有的 `parse_pdf(path, source)`。首轮在线联调可直接沿用现有阅读逻辑。[PDF 解析与缓存](../agent/apis/papers.py)

## 从提交到看到结果

1. **选择模型。** 首轮完整 Agent 使用 `MODEL_PROVIDER=bailian`，在作业中配置百炼地址和 `BAILIAN_API_KEY`。以后使用课程 Qwen 时，先提交 `qwen-public-serve` GPU 作业，等日志显示 `Application startup complete`，取当次 `SERVICE_BASE_URL`。
2. **提交研究任务。** 网页调用 `POST /api/v1/agent-research`，后端记录任务和用户，入队并返回 `202` 和 `task_id`。独立 Worker（`python -m app.runner_worker`）生成输入包，接入后用 `tcloud submit` 提交 CPU 作业并保存作业号。[后端打包](../backend/src/app/agent_bridge/bundles.py) · [Worker](../backend/src/app/agent_bridge/worker.py)
3. **执行 Agent。** 作业入口将论文库地址和令牌传给 `LibraryClient`，调用 `baseline.run_task`。Agent 根据模型的工具调用检索论文、下载并校验原件，再将带页码的文本回填给模型。[Agent 工作流](../agent/baseline.py) · [模型接口](../agent/apis/model.py)
4. **取回结果。** 作业入口应将 `agent-result-v1` 格式的 `result.json` 写入 `TACC_USERDIR` 下本次派发的独立目录。Worker 用 `tcloud ps -j` 查作业、`tcloud download` 取文件，核对任务、派发、输入清单摘要和作业号后入库。结果页轮询后端，用户可从引用打开原 PDF 对应页。作业从队列消失时，仍需核实结果是否交付。[结果校验](../backend/src/app/agent_bridge/results.py) · [结果页](../frontend/src/features/agentResearch/ResultPage.tsx)

## 当前分支还差什么

- **作业入口。** 建议在 `tacc/` 放一个批作业入口。它读取任务和运行配置，调用现有 Baseline，给结果补齐派发标识、输入清单摘要和作业号。有预选论文时，当前打包器会额外附带原件。在线传输适配后，预选论文只需随任务传来源标识与校验值。[Baseline 入口](../agent/baseline.py) · [当前打包器](../backend/src/app/agent_bridge/bundles.py)
- **自动派发。** 本阶段用文件交换模式生成作业凭据，由探测提交脚本送到计算节点。当前 `AGENT_TRANSPORT=tacc` 通过 SSH 调远程 Slurm helper。后续在服务器上接入 `tcloud` 的提交、查询、下载、取消及重启恢复。当前从 Worker 领取起计时，任务时限需覆盖排队和执行。[现有传输](../backend/src/app/agent_bridge/tacc.py)
- **动态来源入库。** 后端当前只接受预选的库内来源及符合规则的 arXiv 来源。需按任务用户、UUID、SHA-256、篇数和页码核对运行中发现的库内论文，保存来源与引用的关联，供网页跳到原文。[结果校验](../backend/src/app/agent_bridge/results.py)

## 已验证：从 TACC 读取本地用户论文库

2026-11-21，单 CPU 作业 `30379` 通过 Cloudflare Quick Tunnel 访问本机的隔离测试后端。两个测试用户各上传了一份同名 PDF。Worker 给研究任务自动签发令牌，TACC 运行 Agent 的 `search_library`、`read_library_paper`，只搜到提交用户的一篇，下载的 1,151 字节、SHA-256 和第 1 页正文均匹配。访问另一用户的 PDF 返回 404。此项验收无需模型 API key。此前作业 `30372` 验证的是已部署站点的健康接口。

复跑时，向本地测试后端开临时 HTTPS 隧道，把地址设为 Worker 的 `AGENT_LIBRARY_PUBLIC_URL`，以 `manual` 文件交换模式启动 Worker，再通过研究页或 API 提交任务。准备 `target.json`，填入测试论文的 `query`、`paper_id`、`sha256`、预期物理页 `page` 和该页上的唯一文本 `marker`，可附 `page_count` 和另一测试用户的 `foreign_paper_id`。在仓库根目录运行：

```sh
bash tacc/library-probe/submit.sh /path/to/outbox/DISPATCH_ID /path/to/target.json
tcloud download api-probe/runs/library-probe-JOBID.json ./report.json
```

用实际派发目录与作业号替换占位符，等作业结束后核对报告中的作业号及 `status=pass`，然后关闭隧道。[探测入口](library-probe/main.py) · [平台命令](README.md)
