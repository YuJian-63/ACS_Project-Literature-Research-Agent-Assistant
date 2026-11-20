# Research Integration Fixes Implementation Plan

**Goal:** 完成提交幂等、账号草稿恢复、验收脚本更新和真实端到端检查。

**Architecture:** 复用后端已有的 Idempotency-Key。同一提交重试和刷新复用随机键，输入改变后生成新键，成功后清理。按账号在当前标签页的 sessionStorage 保存问题、论文 ID 和未确认提交；恢复时重新校验论文权限。退出、会话失效及跨标签页账号事件清理草稿。

**Tech Stack:** React、TypeScript、sessionStorage、Playwright、现有 FastAPI/Agent API。

**Spec:** 用户确认的四项修复顺序及前后端对接审查结果。

## Constraints

- 保留已有未提交修改，不提交或推送 Git。
- 不新增数据库迁移或更改现有 API 响应。
- 存储不可用不导致崩溃；不跨账号展示草稿。
- 真实联调使用隔离账号和资料，不更改既有业务数据，不输出密钥。
- 明确记录真实依赖阻塞，不以模拟测试代替真实通过。

## Tasks

1. [x] 提交幂等：回归先确认缺少请求头，再验证响应丢失后的重试返回同一真实数据库任务。
2. [x] 草稿保留：10 个浏览器回归覆盖刷新、PDF 往返、预选参数、输入变化、成功清理、账号隔离及存储异常。
3. [x] 验收脚本：移除失效夹具依赖，更新断言和浏览器启动方式；统一入口 16/16 项通过。
4. [x] 真实本地联调：真实上传、解析、下载、Agent/模型执行和引用往返通过；任务 succeeded/completed，隔离数据已清理。

## Verification

- 新增回归先失败，再验证修复通过。
- 执行前端类型检查、构建和全部离线浏览器脚本。
- 重跑研究 API、认证及原生 PostgreSQL 测试。
- 记录真实任务 ID、终态和来源校验结果，不记录密钥或会话信息。

验收结果、复跑命令及未覆盖的外部依赖见 [本轮联调记录](../../frontend-backend-acceptance.md)。ECS/TACC、真实 arXiv 和邮件投递不在本次本地通过范围内。
