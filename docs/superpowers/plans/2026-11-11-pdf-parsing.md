# PDF Parsing Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Do not delegate or commit/push without user request.

**Goal:** 在不改变 Mock 研究流程的前提下持久化真实 PDF 文本和物理页码证据。

**Architecture:** 纯解析模块和受监督子进程负责文档读取，独立 Parser Worker 管理数据库租约与原子保存。证据服务面向未来 Runner，前端复用现有资源查询支持有限轮询。

**Tech Stack:** FastAPI/SQLAlchemy/PostgreSQL、pypdf 7.x、React/TypeScript。

**Spec:** `docs/superpowers/specs/2026-11-11-pdf-parsing.md`。

## Global Constraints

- 保留 API 响应结构和数据库约束；不伪造 chunk、引用或真实研究产物。
- 不改写原文件/hash/历史片段；ready/failed 不自动重试。
- 500 页、8 MiB 文本、10000 片段、单页内容流 16 MiB；片段最多 2000 字符；子进程默认 120 秒。
- 租约 60 秒、20 秒续租；任何失效 owner 不得提交片段。
- 临时测试仅在 runtime，依赖通过 uv.lock 固定；不自动提交 Git。

## Review Focus

- 空白物理页不能导致后续引用页码偏移，超限不可静默截断。
- 失败提交/失去租约不可留下 ready 或半套 chunks。
- 解析挂起/崩溃不得卡住父 Worker 的心跳或关停。
- 前端筛选/卸载需取消旧轮询，错误不得清掉已知论文。
- Mock 上传/任务 API 保持兼容，解析完成不声称 Agent 已分析。

## Tasks

- [x] 解析核心：新增 `backend/src/app/pdf_parser.py`，更新依赖，先用 runtime 校验失败再实现；验证多页、空页、chunk/hash、加密/坏文件/边界。
- [x] Worker 与证据：新增 `parse_lifecycle.py`、`parser_worker.py`、`evidence.py`，更新配置；验证领取/续租/回收/原子写入/只读分页和子进程终止。
- [x] 前端衔接：更新 useResource、论文库/选择器/上传文案及失败详情，验证非重叠轮询、终态停止、错误保留和现有流程。
- [x] 联调与交付：执行核心/数据库/真实进程/浏览器及旧 Mock 回归、前端构建，更新 API/数据库/启动/Agent 对接说明，记录环境限制。

## Verification Record

- `uv sync --project backend --locked`、Python app `compileall`、PDF parser core/boundary checks 通过；pypdf 7.0.1 已固定进 `uv.lock`。
- Parser lifecycle 在 PGlite PostgreSQL-compatible socket 上验证 atomic chunks/ready、分页 evidence、Mock 对 uploaded paper 的既有容忍、坏/加密/空 PDF、文件篡改/缺失、租约恢复与旧 owner 写入拒绝、插入回滚、子进程 timeout 和 shutdown。
- 最小进程超时边界还验证了即使 child 刚退出也不会接受超过 deadline 的结果；解析子进程不继承 DATABASE_URL/STORAGE_ROOT 等秘密配置。
- 真实 FastAPI + 独立 Parser Worker + Chromium 验证状态轮询、保留新建草稿、真实多页提取、失败原因、页码 1/3、内部 evidence、无公开 chunk 路由与窄屏无文档溢出。
- 旧 Mock API 14 项及独立 API/Mock Worker 进程回归通过；DDL/Alembic/ORM 等价检查 85 字段、142 约束、29 索引通过，在线 Alembic autogenerate drift check 通过。
- 前端类型检查、生产构建、核心校验、开发/生产预览 Chromium 故障注入通过；审阅了 Parser ready 桌面和 failure 移动截图。
- Docker Desktop/daemon 未运行；所有 PostgreSQL 集成使用 PGlite 兼容 socket，不等价于 PostgreSQL 17+ 多连接锁竞争。解析子进程也不是 OS 容器沙箱；16 MiB 流上限在解码后执行，不是 RAM 硬限制。无 OCR/Agent，无发布测试框架，无自动 Git commit/push。
