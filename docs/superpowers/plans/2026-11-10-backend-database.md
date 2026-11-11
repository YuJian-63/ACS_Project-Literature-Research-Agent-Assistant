# 后端数据库基础设施实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已确认的七表设计落地为 SQLAlchemy 模型、Alembic 初始迁移和可复现的本地数据库开发环境。

**Architecture:** 使用同步 SQLAlchemy 2 与 psycopg 3。数据库配置从环境变量或 backend/.env 读取；模块导入不建立连接。迁移冻结初始 DDL，不动态读取当前模型或 schema.sql。

**Tech Stack:** Python 3.11+、SQLAlchemy 2.0、Alembic 1.x、psycopg 3、pydantic-settings、uv、PostgreSQL 17+。

**Spec:** `docs/database-design.md`、`docs/api-contract.md`、`backend/sql/schema.sql`。

## Global Constraints

- 保留七张表、原有 CHECK/外键/唯一约束和 13 个显式索引。
- citations_selected_paper 保持 DEFERRABLE INITIALLY DEFERRED。
- 配置不含真实凭据，不在日志或错误中输出连接密码；不自动建表或自动迁移。
- 模型配置和初始迁移不依赖 pgvector、模型服务或 LangGraph。
- 本轮不实现 HTTP 业务接口、不连接已有业务数据库、不创建分支或提交。
- 项目尚无测试框架，本轮使用 runtime 下临时校验脚本，不引入测试框架依赖。

## Review Focus

- DATABASE_URL 含百分号或特殊字符时，驱动和迁移不得经过 INI 插值破坏密码。
- 缺少配置或不是 PostgreSQL 时应明确失败；错误不得回显密码。
- 模块导入和离线迁移不得意外连接默认数据库。
- ORM 和冻结迁移必须与参考 DDL 保持约束一致，特别是延迟引用与级联。
- 在线迁移的 upgrade、重复 upgrade、downgrade 和重新 upgrade 应可验证。

## Task 1: 数据库配置与 ORM

**Files:** backend/pyproject.toml、backend/uv.lock、backend/src/app/config.py、backend/src/app/db/base.py、backend/src/app/db/models.py、backend/src/app/db/session.py。

**Interfaces:** Settings.database_url 为 SecretStr；create_database_engine(settings) 返回 Engine；create_session_factory(engine) 返回 sessionmaker；Base.metadata 提供完整七表结构。

- [x] 先写临时校验，确认缺少配置/模型时失败。
- [x] 实现配置、七表映射及显式 Engine/Session 工厂。
- [x] 验证环境优先级、密码脱敏、URL 驱动、元数据及生成 SQL。

## Task 2: Alembic 迁移与本地环境

**Files:** backend/alembic.ini、backend/alembic/env.py、backend/alembic/script.py.mako、backend/alembic/versions/20261110_0001_initial_schema.py、backend/.env.example、backend/compose.yaml。

**Interfaces:** 初始 revision 为 20261110_0001，down_revision 为 None；在线从 Settings 获取连接，离线使用 PostgreSQL 方言且不读取凭据。

- [x] 先验证迁移缺失或离线生成失败。
- [x] 实现冻结初始迁移、逆序删表及 Alembic 环境。
- [x] 检查离线 SQL、迁移版本图和 Compose 配置。
- [x] 使用隔离测试引擎验证升级/降级及七表约束，不冒充真实多连接并发测试。

## Task 3: 操作说明与整体校验

**Files:** backend/README.md、README.md、docs/database-design.md。

**Interfaces:** 文档命令从 backend 目录运行，先复制 .env.example，再启动数据库并执行 Alembic；DDL 与迁移不得重复应用。

- [x] 写清安装、配置、启动、迁移、检查、停止和后续 API 接入步骤。
- [x] 执行完整临时校验、语法/锁文件/空白检查及独立代码审查。
- [x] 记录通过结果和原生 PostgreSQL/并发等尚未验证的边界。
