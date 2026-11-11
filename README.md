# ACS_Project-Literature-Research-Agent-Assistant
HKUST CSIT6000V Advanced AI Computing and Systems Project: Literature Research Agent Assistant

## 项目文档

- [项目提案](docs/Proposal.md)
- [API 契约](docs/api-contract.md)
- [数据库设计](docs/database-design.md)
- [后端安装、API 与 Worker 启动](backend/README.md)
- [前端安装、运行与验收](frontend/README.md)

当前已提供接口规范、数据库设计、SQLAlchemy 模型、Alembic 初始迁移、FastAPI API 和独立 Mock Worker，以及 React 前端论文库、PDF 上传、新建任务、任务列表与结果工作台。模拟结果不代表论文分析，真实 PDF 解析和 Agent 集成留待后续阶段。

## 本地运行

先按后端文档启动 PostgreSQL、执行迁移，在两个终端分别运行 API 和 Worker。再在第三个终端执行：

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

访问 `http://127.0.0.1:5173`，依次上传 PDF、选择论文、创建任务并查看结果。仅用于受信本机单用户环境；未启动 Worker 时任务保持排队。Node.js 版本和部署代理说明见前端文档。
