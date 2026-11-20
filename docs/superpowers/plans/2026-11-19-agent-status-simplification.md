# Agent 状态统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 按用户选择的第一种方案保留 status.json，将远程任务状态与后端主状态对齐。

**Architecture:** 后端保留 queued/running/succeeded/failed；Agent 启动后只发布 running/succeeded/failed。completed/partial 映射为 succeeded，其余研究停止原因映射为 failed，保留完整结果和原始 stop_reason。CLI 与持久化状态使用同一映射函数。

**Tech Stack:** Python 3.12、pytest、现有 Agent 文件交换协议。

**Spec:** 本文记录用户已选择的第一种方案；不移除 status.json，不改 Agent 研究流程、后端数据库或 TACC 传输边界。

## Global Constraints

- 沿用 agent-job-status-v1 字段及 CLI 退出码 0/1/2，不调用真实模型、数据库或 TACC。
- 旧 finished 状态仅兼容读取；必须重新验证已有结果后，按 stop_reason 修正为新状态。
- 成功或失败的完整结果都可安全复用；无结果的失败、运行中或崩溃状态不自动执行。
- 保留身份校验、独占锁、结果原子发布及原有未提交改动；本次不提交或推送。

## Review Focus

- 研究失败仍有 result.json，不能因此被标记为成功或再次调用模型。
- partial 仍可展示，不能因未解决项被直接改为失败。
- CLI、首次执行和结果复用必须返回相同状态。
- 旧 finished 文件不能让损坏或错任务结果绕过校验。
- succeeded 状态但结果缺失应返回 INCOMPLETE，不执行新调用。

### Task 1: 统一作业状态并补充回归

**Files:** agent/agent_io/job.py、agent/tests/test_dispatch_job.py，以及 Agent README/接口说明、后端对接说明和终端手册。

- [x] 修改原有状态断言，增加全部 stop_reason、CLI、重复结果复用、旧 finished 兼容、缺失结果与错误身份测试；先运行并确认旧实现失败。
- [x] 实现单一结果状态映射，统一首次发布、重放和 CLI；只兼容读取旧 finished。
- [x] 更新文档中的状态约定与预期结果，保留此前验收记录并标注旧协议已被本计划更新。
- [x] 运行目标测试、Agent 全量离线测试、后端离线回归、Ruff 和差异检查，记录实际结果。

## 验证结果

- RED：修改状态测试后，旧实现出现 16 项失败，原因是仍发布 finished、且不接受已有 succeeded 状态。
- GREEN：ZIP 与作业入口测试 65 通过，覆盖所有 11 个研究 stop_reason 的首次发布、结果复用和 CLI 退出码/状态一致性。
- Agent 全量离线测试 203 通过、4 跳过；后端 193 项中 123 通过、70 数据库用例跳过。
- Ruff lint/format 与 git diff --check 通过；未修改实际 .env、数据库或前端代码，未访问真实模型或 TACC。
- 保留 status.json 与既有协议字段、锁和输入身份检查；本轮没有提交或推送 Git。
