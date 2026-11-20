# v3 本机运行

所有命令在 v3 目录中执行，不读取其他版本的 `.env` 或虚拟环境。

```bash
# backend/
uv sync --frozen
docker compose up -d --wait
uv run alembic upgrade head
uv run alembic check
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8002
```

Parser、Import、Mail Worker 分别以 `uv run python -m app.parser_worker`、`app.import_worker`、`app.mail_worker` 启动。前端在 `frontend/` 中 `npm run dev`，打开 http://127.0.0.1:5175。

后端健康检查 http://127.0.0.1:8002/ready 。数据库端口 55435，文件目录 `backend/runtime/v3/storage`。业务数据从空库开始，旧账号不会出现在这里。

停止自己的前后端/Worker 使用对应终端 Ctrl+C。`docker compose stop` 仅停止命名为 v3 的容器并保留数据卷。不要执行删除数据卷操作，除非明确需要销毁 v3 数据。
