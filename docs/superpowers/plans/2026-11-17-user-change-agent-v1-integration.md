# 用户改动：Agent v1 Integration Plan

**Goal:** 接通已确认的 Agent v1，保留旧任务兼容。
**Spec:** ../specs/2026-11-17-user-change-agent-v1-integration-design.md（用户已确认）
**Architecture:** 专用子进程运行 run_task，任务表保存 agent_input/agent_result JSONB；新 runner agent，旧流程保留。
**Tech Stack:** FastAPI、SQLAlchemy/Alembic、Python 3.12 Agent、React。

## Global Constraints

新记录 user-change；不修改 Agent 源码，不覆盖历史结果；不自动推送或提交。
在现有 backend-dev 工作区实施，使用独立临时环境；不动现有数据库。

## Interfaces

- POST /api/v1/tasks 接受旧 TaskCreate 或新 AgentTaskCreate（sources/allow_search 等 v1 字段，另允许 task_type 仅用于 UI）。
- GET Task 增加 result_format（legacy/agent-v1）和 agent_input（可空）；旧 budget 字段新模式 max_tokens=null，不承诺累计 Token 限制。
- GET /api/v1/tasks/{id}/agent-result：完成后返回 TaskResult（去掉 trace/configuration），执行中为 null；失败也可返回。
- GET /api/v1/tasks/{id}/agent-trace：返回 {trace,configuration}，仅本人可读。
- subprocess_client.run_agent(task:dict, *, python:str, timeout_seconds:float, stopped:Callable[[],bool]) -> dict；异常 AgentProcessError(code,message)。
- Settings agent_python 默认 agent/.venv/bin/python；启用 TASK_RUNNER=agent 接管旧 paper_ids 请求；显式 sources 请求直接选择 agent。

## Review Focus

跨用户与任务 ID 不匹配、迟到结果；超时终止；完整原生输出及 null usage；旧任务兼容；未配置 Agent 环境不能伪成功。

### Task 1: 进程桥接
- [ ] 先测缺少环境、子进程异常、超时、停止、完整 JSON 与 task_id。
- [ ] 桥接脚本调用真实 run_task(...,persist=False)，文件协议与有限输出。
- [ ] 离线真实 Agent 假模型测试，使用独立 Python 3.12 环境。

### Task 2: 后端任务
- [ ] 先编写新输入及结果生命周期测试并观察失败。
- [ ] 新迁移和模型字段；agent runner；幂等/归属/容量沿用既有规则。
- [ ] Worker 领取/心跳/超时/结果持久化，结果与 trace 分离查询。
- [ ] API 与旧 paper_ids 兼容，回归并验证迁移 SQL。

### Task 3: 前端
- [ ] 新 Agent 模式输入，保持旧模式；Agent 原生结果、Markdown 表格、引用与部分完成展示。
- [ ] 失败任务读取结果；刷新恢复；不把 Agent ID 当本地 PDF ID。
- [ ] typecheck/build 与适当检查。

### Task 4: 集成验收
- [ ] 完整回归、独立审查；追加 user-change 开发证据。
- [ ] 区分离线、PostgreSQL 与真实模型验收，不具备密钥时如实说明。

## 执行进度追加

2026-11-17：Task1—3已实现，Task4已完成离线/隔离数据库/构建及独立审查。
149项后端测试通过、62旧数据库专项跳过；65项Agent测试通过、1跳过。
真实模型、联网来源与浏览器交互验收尚未执行，不能据此宣称已完成线上验收。
详见 docs/2026-11-17-user-change-agent-v1-integration.md。
