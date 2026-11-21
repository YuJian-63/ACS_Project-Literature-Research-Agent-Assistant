# Literature Research Assistant — v3

v3 保留登录、改密、论文搜索、导入、论文库/PDF 阅读以及统一研究界面。问题必填，参考论文可选。旧三类研究工作流、单独 LLM 执行器和模拟结果存储已从当前应用移除；已合入 main 的统一研究接口与 Agent 执行适配代码；上游尚缺运行包装文件，真实执行限制见下方合并说明。

本版本使用独立的 PostgreSQL 容器、数据卷、数据库、账号、文件存储和会话。新数据库没有复制旧账号、论文或研究记录，需要重新注册并导入资料。

| 项目 | v3 |
| --- | --- |
| 前端 | http://127.0.0.1:5175 |
| 后端 | http://127.0.0.1:8002 |
| PostgreSQL | 127.0.0.1:55435 / literature_v3 |
| 容器 / 数据卷 | literature-v3-postgres-1 / literature_v3_postgres_data |
| PDF 存储 | backend/runtime/v3/storage |
| 本地会话 Cookie | lra_v3_session |

## 首次配置

```bash
python3 backend/scripts/init_local_env.py
cd backend
uv sync --frozen
docker compose up -d --wait
uv run alembic upgrade head
```

初始化脚本拒绝覆盖已有 `.env`，不会读取其他版本的配置。请在自己的 `backend/.env` 中设置邮件服务和 arXiv 联系邮箱；密钥和数据库密码由脚本独立生成。不要提交 `.env`、数据库卷或论文文件。

## 启动

分别在终端执行，始终位于 v3 的目录中：

```bash
# backend/
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8002
```

```bash
# backend/，按功能启动
uv run python -m app.parser_worker
uv run python -m app.import_worker
uv run python -m app.mail_worker
```

```bash
# frontend/
npm ci
npm run dev
```

前端默认代理到 8002，不需要使用其他版本的 Python、环境文件或后端。浏览器请使用 `127.0.0.1:5175`，与邮件链接和来源校验配置保持一致。

完整交接说明：[docs/v3-frontend-backend-handoff.md](docs/v3-frontend-backend-handoff.md)。

最新合并状态及运行限制：[v3 与 main 冲突处理说明](docs/v3-main-merge-resolution.md)。
