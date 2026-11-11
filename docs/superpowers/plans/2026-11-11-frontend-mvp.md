# Frontend MVP Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. No delegation or Git commit/push without user request.

**Goal:** 完成可与现有 FastAPI/Mock Worker 联调的研究工作台。

**Architecture:** Vite 单页应用，以类型化 Axios 客户端对接现有契约；路由页面按需加载，共享请求取消、错误展示、论文选择与任务轮询逻辑。不新增后端接口。

**Tech Stack:** React/TypeScript、Vite、Ant Design、React Router、Axios、React Markdown。

**Spec:** `docs/superpowers/specs/2026-11-11-frontend-mvp.md`、`docs/api-contract.md`。

## Global Constraints

- 后端字段 snake_case，上传单文件最大 20 MiB，客户端校验不代替服务端校验。
- 轮询间隔 2 秒，禁止重叠；任务终态、网络故障、结果查询故障分开处理。
- 所有模拟内容明确标记；Markdown 无原始 HTML；未知用量为 null。
- 当前仓库没有测试框架，不引入发布测试框架；临时校验、浏览器脚本与截图写入忽略的 runtime。

## Review Focus

- 快速切换筛选/路由后旧响应不得覆盖新状态；卸载取消请求。
- 连续点击与提交网络中断不能产生重复任务；重试复用幂等键。
- 单篇/多篇切换、跨页选择及重跑后保持正确输入，不悄悄丢弃论文。
- 查询失败不能将持久化任务状态改成 failed；终态结果拉取失败应可重试。
- 长文件名、无数据、无 Worker、窄屏和不安全 Markdown 都有可用的展示。

## Tasks

- [x] 基础与契约：创建 package/锁文件、Vite/TS 配置、API 类型和客户端、请求状态及输入校验；临时脚本校验规范化和错误分支。
- [x] 论文与创建：完成工作台外壳、论文库、上传、跨页选择和新建任务；校验文件边界与幂等重试。
- [x] 任务与结果：完成列表、可取消无重叠轮询、事件游标、Markdown、统计和失败重跑；浏览器验证网络恢复和终态停止。
- [x] 联调与交付：类型检查、生产构建、浏览器桌面/移动截图及真实 API/Worker 冒烟，更新安装说明与实际验收边界。

## Verification Record

- `npm.cmd --prefix frontend run build`：应用/配置类型检查和 Vite 生产构建通过，路由及 Markdown 按需加载。
- 临时核心校验：输入规范化、签名、选择数量、文件名/头和精确 20 MiB 边界通过。
- Chromium 故障注入在开发模式和生产预览通过：跨页选取、同键重试/连续点击、查询故障状态保留、游标去重、终态事件补齐、产物重试、终态刷新失败不恢复轮询、不安全 Markdown、路由离开停止查询、390px 页面无横向溢出。
- 真实浏览器经 Vite 代理调用独立 API/Worker，验证上传、摘要完成、刷新恢复、事件/产物/原文件、重跑和预算失败；使用 PGlite 兼容 socket，不代替原生 PostgreSQL 并发事务验收。
- 已查看桌面论文库、真实完成/失败详情及移动端新建/列表/空状态截图；修复移动导航重复高亮、文字换行与过长选择区。
- 验收脚本/截图/测试数据仅在忽略的 `runtime/`；没有引入发布测试框架，没有提交或推送 Git。
