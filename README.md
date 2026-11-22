# Literature Research Agent Assistant

HKUST CSIT6000V Advanced AI Computing and Systems 课程项目。用户在网页上传 PDF，提交研究问题，可预选论文或让 Agent 搜索自己的论文库。课程模式下，后端 Worker 派发 TACC CPU 作业，按网页选择的 Baseline 或 Extension 调用百炼。答案回到网页后，点击引用即可打开原 PDF 的对应页。

## 项目结构

| 目录 | 职责 |
| --- | --- |
| [frontend/](frontend/README.md) | 浏览器里的研究工作台。上传或导入论文、提交问题、查看结果和引用原文。 |
| [backend/](backend/README.md) | API 管理账号、论文库和任务。研究 Worker 向 TACC 提交作业，取回结果并写入 PostgreSQL。PDF 原件保存在后端文件目录。 |
| [agent/](agent/README.md) | 研究逻辑。Baseline 和 Retrieval Extension 在这里实现论文检索、PDF 阅读、模型调用和带引用的回答。 |
| [tacc/](tacc/README.md) | 课程集群上的作业入口、环境配置和探测脚本。CPU 节点通过 [research/run_job.py](tacc/research/run_job.py) 读取任务清单并调用 Agent。 |
| [qwen-public-serve-agent/](qwen-public-serve-agent/README-AGENT.txt) | 单独提交到 TACC GPU 节点的课程 Qwen 模型服务。当前已验收的研究流程使用百炼 API。 |
| [scripts/](scripts/local-research) | 本机联调入口。一键启动服务、查看日志和查询 TACC 作业号。 |
| [docs/](docs/) | 跨组件的 API 契约、数据库设计和派发协议。 |

## 运行

新设备先运行 `./scripts/local-research configure` 创建配置表，填好仓库根目录的 `.env.local-research` 后再运行一次。完成首次安装和数据库迁移后，在仓库根目录运行 `./scripts/local-research up`，打开终端显示的网页。用 `./scripts/local-research jobs` 查看 TACC 作业号。[本机一键启动](tacc/TACC.md#本机一键启动)

- **使用已启动的预览。** 登录后在「论文库」上传 PDF，在「新建研究」提问，然后从「研究记录」查看答案和引用。[网页操作与真实作业验收](tacc/TACC.md)
- **从头启动。** 准备 PostgreSQL 并运行迁移，配置 API、Parser 和研究 Worker，再启动前端。[后端启动](backend/README.md) · [TACC 作业配置](tacc/TACC.md#从头启动本机环境) · [前端启动](frontend/README.md)

## 开发文档

- [前后端 API 契约](docs/api-contract.md) · [数据库设计](docs/database-design.md)
- [后端与 Agent 的派发协议](docs/agent-backend-integration.md)
- [本地运维与测试](docs/terminal-operations.md) · [项目提案](docs/Proposal.md)
