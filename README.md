# ACS_Project-Literature-Research-Agent-Assistant
HKUST CSIT6000V Advanced AI Computing and Systems Project: Literature Research Agent Assistant

## 项目文档

- [项目提案](docs/Proposal.md)
- [API 契约](docs/api-contract.md)
- [数据库设计](docs/database-design.md)
- [后端安装、API 与 Worker 启动](backend/README.md)
- [前端安装、运行与验收](frontend/README.md)

后端代码已按 `api`、`papers`、`research`、`sources`、`tasks`、`workers` 分包，当前目录与职责见 [后端文档第 3 节](backend/README.md#3-代码入口)。原有 API 与 Worker 启动命令保持不变。

当前已提供接口规范、数据库设计、SQLAlchemy 模型、Alembic 初始迁移、FastAPI API、独立 PDF Parser Worker 和 Mock 任务 Worker，以及 React 前端论文库、PDF 上传/解析状态、新建任务、任务列表与结果工作台。解析出的原文片段供后续 Agent 内部读取；模拟任务仍不代表论文分析或研究结论。

MVP-3 增量已提供 arXiv 关键词搜索、指定版本 PDF 导入、持久化导入记录和独立 Import Worker；默认关闭联网功能。2026-11-13 用户完成隔离原生 PostgreSQL 17.6 的八组专项验收，并确认真实 arXiv 搜索、单版本下载、解析、浏览器展示及 Mock 任务闭环通过。开启步骤见后端文档第 9 节；不需要模型密钥即可搜索、下载和解析。详细证据和验收边界见 [MVP-3 实施记录](docs/superpowers/plans/2026-11-12-mvp-3-arxiv-search-import.md)。

真实模型联调已完成 DeepSeek 单篇摘要、单篇问答及一次双论文综述的用户人工验收，覆盖正文、来源引用、PDF 物理页码与刷新恢复。2026-11-14 新建真实综述改为服务端自动预算：逐篇分析，再分别生成三段综述，服务端组装比较表和引用；用户无需填写预算。已通过离线模型、隔离 PostgreSQL 和浏览器验证，用户已完成新流程的真实六篇论文人工验收，任务 `eb3b4c9e-39db-4e19-bd88-5e64faeb9941`；确认正文完整、六行比较表、引用抽查和刷新恢复正常。历史任务保留原工作流与输出上限，见 [分阶段综述实施记录](docs/superpowers/plans/2026-11-14-staged-review.md)。已有人工验收不代表普遍生成可靠性，arXiv 超时也不由此次调整解决。

## 本地运行

先按后端文档启动 PostgreSQL 并执行迁移，在两个终端分别运行 API 和 Mock Worker；如需真实提取 PDF 文本，在第三个后端终端启动 Parser Worker。最后在第四个终端启动前端：

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

访问 `http://127.0.0.1:5173`，依次上传 PDF、选择论文、创建任务并查看结果。仅用于受信本机单用户环境；未启动 Worker 时任务保持排队。Node.js 版本和部署代理说明见前端文档。
