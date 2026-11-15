# 用户改动：Evidence API Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 外部 Agent 可分页读取已解析论文的原文片段。
**Architecture:** 在既有 papers 路由包装 read_evidence，复用状态检查与分页逻辑。
**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、unittest。
**Spec:** ../specs/2026-11-14-user-change-evidence-api-design.md（用户已于本会话确认）

## Global Constraints

- 新记录使用 user-change，表示用户发起改动；历史记录不修改。
- 不改用户 README 修改，不迁移数据库，不改变内部读取函数。
- after_index 默认 -1 且 >= -1；limit 默认 100，范围 1—100。
- 沿用受信本机单用户部署边界。

## Review Focus

- 游标起点及越界空页保持正确的下一页游标。
- 论文 uploaded/processing/failed 均拒绝读取。
- 非法 UUID、非整数和越界参数使用统一 422。
- 完整返回原文、哈希和物理页码，不暴露内部路径。
- OpenAPI 描述真实响应类型。

### Task 1: 只读分页接口与验证

**Files:** 新建 backend/tests/test_evidence_api.py；修改 backend/src/app/api/papers.py、schemas.py。
**Interfaces:** 消费 read_evidence(sessions, paper_id, after_index=-1, limit=100)，产生 GET /api/v1/papers/{paper_id}/evidence。

- [ ] 编写 HTTP 测试，覆盖默认值、分页衔接、空页、状态和参数错误、OpenAPI。
- [ ] 运行测试确认新路径尚不存在导致失败。
- [ ] 添加 EvidenceChunkResponse、EvidencePage 与只读路由。
- [ ] 运行新增测试及完整 unittest discover；PostgreSQL 未配置的测试如实标记跳过。
- [ ] 独立审查改动，新增 user-change 开发记录和调用说明。

## 执行约定

在现有 backend-dev 工作区直接实施，用户确认后继续完成，无需再次选择执行方式。
不自动提交或切换分支。隔离虚拟环境放 /private/tmp，测试不接触实际数据库。

## 执行进度追加（2026-11-14）

- Task 1：测试先失败后通过，路由和响应模型已实现。
- 完整测试：39 项，31 通过、8 PostgreSQL 条件测试跳过。
- 实际数据库约束和并发未验证；未执行 git 提交。
- 新增对接及开发记录：docs/2026-11-14-user-change-evidence-api.md。
- Task 1 完成：独立审查无 Critical/Important 问题，新增 5 项测试亦经审查者复跑通过。
