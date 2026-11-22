# Literature Research Agent Assistant

HKUST CSIT6000V Advanced AI Computing and Systems 课程项目。用户在网页上传 PDF，提交研究问题，可预选论文或让 Agent 搜索自己的论文库。课程模式下，后端 Worker 派发 TACC CPU 作业，按网页选择的 Baseline 或 Extension 调用百炼。答案回到网页后，点击引用即可打开原 PDF 的对应页。

## 项目结构

| 目录 | 职责 |
| --- | --- |
| [frontend/](frontend/README.md) | 浏览器里的研究工作台。上传或导入论文、提交问题、查看结果和引用原文。 |
| [backend/](backend/README.md) | API 管理账号、论文库和任务。研究 Worker 向 TACC 提交作业，取回结果并写入 PostgreSQL。PDF 原件保存在后端文件目录。 |
| [agent/](agent/README.md) | 研究逻辑。Baseline 和 Retrieval Extension 在这里实现论文检索、PDF 阅读、模型调用和带引用的回答。 |
| [tacc/](tacc/README.md) | 课程集群上的作业入口、环境配置和探测脚本。CPU 节点通过 [research/run_job.py](tacc/research/run_job.py) 读取任务清单并调用 Agent。 |
| [model-server/](model-server/README.md) | 单独提交到 TACC GPU 节点的课程 Qwen 模型服务。当前已验收的研究流程使用百炼 API。 |
| [scripts/](docs/service_launch.md#按系统使用脚本) | Windows、Linux、macOS 初始化与启动脚本；另保留 TACC 联调和 ECS 服务入口。 |
| [docs/](docs/) | 数据库设计、API 接口、项目提案及前后端启动说明。 |

## 运行

普通本地开发使用对应系统的 `scripts/service-*` 脚本，首次执行 `init`，之后执行 `start`。[各系统命令与配置](docs/service_launch.md#按系统使用脚本)

- **TACC 本机联调**使用 `./scripts/local-research configure` 配置，再按 [课程启动流程](tacc/TACC.md#本机一键启动) 准备依赖与迁移并运行 `./scripts/research up`。留空 `backend/.env` 的 `AGENT_LIBRARY_PUBLIC_URL` 会自动启动 Cloudflare 隧道；已有固定入口时填入其 HTTPS 地址。
- **已部署的 ECS** 运行 `./scripts/research up`，通过已安装的 `acs-api.service` 识别。先在服务器的 `backend/.env` 填好 TACC 能访问的论文库地址，如 `AGENT_LIBRARY_PUBLIC_URL=https://library.example.com`。用有权启动这些 systemd 服务的账号运行，API 和 Worker 由 systemd 管理，Nginx 提供已发布的前端。新版本继续由推送到 `main` 触发自动部署。

在网页「模型管理」中选择「全站研究并发数」（1–4）即可在线调整，所有登录账号共用此设置。

- **使用已启动的预览。** 登录后在「论文库」上传 PDF，在「新建研究」提问，然后从「研究记录」查看答案和引用。[网页操作与真实作业验收](tacc/TACC.md)
- **从头启动。** 准备 PostgreSQL 并运行迁移，配置 API、Parser 和研究 Worker，再启动前端。[后端启动](backend/README.md) · [TACC 作业配置](tacc/TACC.md#首次配置从新账号注册到网页研究) · [前端启动](frontend/README.md)

## 开发文档

- [前后端 API 契约](docs/api-contract.md) · [数据库设计](docs/database-design.md)
- [前后端启动与联调](docs/service_launch.md) · [项目提案](docs/Proposal.md)
