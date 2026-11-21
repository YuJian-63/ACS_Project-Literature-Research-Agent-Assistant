# 前后端研究验收记录

2026-11-21，预选论文和空预选查库两种方式均完成了真实 Chrome、后端 Worker、课程 TACC 和百炼联调。从正文引用可以打开上传 PDF 的第 2 页。操作步骤、测试论文及作业号统一见 [TACC 操作指南](../tacc/TACC.md)。界面操作和离线回归入口见[前端说明](../frontend/README.md)。

## 修改后端后如何复核

在 `backend/` 运行下列定向测试。它们分别验证课程 SDK 提交回执、超时与恢复，以及 Worker 交付行为，使用测试替身完成。

```sh
uv run --locked python -m unittest discover -s tests -p test_agent_tcloud.py
uv run --locked python -m unittest discover -s tests -p test_agent_worker.py
```

要核对数据库中的用户隔离、预选顺序和运行时发现的来源，使用[PostgreSQL 集成测试](../backend/tests/test_agent_postgres.py)，将 `AGENT_TEST_DATABASE_URL` 指向可清空的专用测试库。真实集群验收时，分别从网页提交一次预选和空预选，在结果页点开引用，核对原件和物理页码。

## 2026-11-20 本地传输历史验收

`backend-dev-v2` 曾以临时账号、一页合成 PDF 和独立 PostgreSQL 完成本地 Agent 验收。浏览器上传论文，提交响应丢失后复用幂等键，数据库只创建一个任务。模型返回中文答案和一条引用，点击后打开原件第 1 页，再返回同一条引用。验收结束后已清理临时数据库。

[当时的本地验收脚本](../backend/checks/live_research_acceptance.py)依赖 `AGENT_TRANSPORT=local` 和 `AGENT_LOCAL_ROOT/run_dispatch.py`。当前分支内置的作业入口在 [tacc/research](../tacc/research)，在此分支复跑真实链路请使用上面的 TACC 流程。
