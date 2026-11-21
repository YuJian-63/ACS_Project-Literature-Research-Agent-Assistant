# Literature Research Agent Assistant

HKUST CSIT6000V Advanced AI Computing and Systems 课程项目。用户在网页上传 PDF，提交研究问题，可预选论文或让 Agent 搜索自己的论文库。课程模式下，后端 Worker 派发 TACC CPU 作业，独立 Baseline Agent 调用百炼。答案回到网页后，点击引用即可打开原 PDF 的对应页。

## 运行

- **使用已启动的预览。** 登录后在「论文库」上传 PDF，在「新建研究」提问，然后从「研究记录」查看答案和引用。[网页操作与真实作业验收](tacc/TACC.md)
- **从头启动。** 准备 PostgreSQL 并运行迁移，配置 API、Parser 和研究 Worker，再启动前端。[后端启动](backend/README.md) · [TACC 作业配置](tacc/TACC.md#从头启动本机环境) · [前端启动](frontend/README.md)

## 开发文档

- [前后端 API 契约](docs/api-contract.md) · [数据库设计](docs/database-design.md)
- [独立 Agent 开发与示例](agent/README.md) · [后端与 Agent 的派发协议](docs/agent-backend-integration.md)
- [本地运维与测试](docs/terminal-operations.md) · [项目提案](docs/Proposal.md)
- [main 自动部署到 ECS](docs/ecs-auto-deploy.md)
