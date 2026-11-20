# v3 backend

当前后端只保留账号、论文上传/读取/解析、arXiv 搜索/导入，以及无类别的研究记录基础模型/API。没有旧摘要、问答、综述工作流，没有旧 LLM/Mock Worker，也没有 SQLite 模拟结果服务。

- 独立数据库：`literature_v3`，仅允许该数据库或 `literature_v3_test_*` 测试数据库。
- 独立初始迁移：`alembic_v3/versions/v3_0001_initial_isolated_v3_schema.py`。
- 新研究表：`agent_research`、`research_papers`；没有 `tasks`、`task_events`、`artifacts`、`citations` 等旧表。
- `POST /api/v1/agent-research` 校验必填问题、可选 0—20 篇论文和默认允许搜索的请求，当前返回 `503 AGENT_NOT_CONNECTED`，不会创建假任务。
- `GET /api/v1/agent-research`、详情和删除读取独立 PostgreSQL，按用户隔离；运行中的研究不允许删除。
- 论文被新研究引用时禁止删除；删除研究释放引用。
- 邮件服务、Parser Worker、Import Worker 使用当前 v3 环境和数据库。

## 配置与运行

参见根目录 README。`scripts/init_local_env.py` 生成私有 `.env`，不覆盖已有文件。Docker Compose 的项目/卷名和端口固定为 v3，避免误接其他版本。生产部署需要修改为自己的独立配置及 HTTPS 来源。

```bash
uv sync --frozen
docker compose up -d --wait
uv run alembic upgrade head
uv run alembic check
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8002
```

## 检查

```bash
PYTHONPATH=src uv run python -m unittest discover -s tests
uv run python tests/test_auth.py --postgres
```

认证 PostgreSQL 检查仅创建并清理独立 `literature_v3_test_auth_*` 数据库；不重置实际数据库。业务端到端检查也使用临时测试数据库，不应往空的 v3 正式库插入测试账号或论文。

任何真实 Agent 适配均应新增在统一接口之后，不恢复旧类别执行器。`agent/` 是保留的独立 Agent 源码，尚未自动连接到此后端。
