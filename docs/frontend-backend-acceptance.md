# 前后端本地验收记录

日期：2026-11-20。分支：`backend-dev-v2`，包含工作区尚未提交的适配代码；本轮不提交或推送 Git。

## 本轮修复

1. 新建研究发送 `Idempotency-Key`；同一未确认请求在重试、刷新后复用键，输入变化后生成新键，成功后清理。
2. 按账号保存当前标签页的研究草稿。PDF 往返、刷新及预选入口返回时恢复问题和最新选择；退出、会话失效及跨标签页账号事件清理；存储不可用时降级。
3. 删除旧研究夹具依赖，统一为 V3 原生研究结果断言，修正搜索按钮及阅读器断言，使用真实格式 UUID。
4. 移除验收脚本硬编码的 macOS Chrome 路径，增加自动启动并关闭独立 Vite 的统一离线入口和独立真实联调入口。

## 自动化结果

| 检查 | 实际结果 | 说明 |
| --- | --- | --- |
| TypeScript 与生产构建 | 通过 | 仍有既有的大于 500 kB 分包提示 |
| 前端单元检查 | 3 个脚本通过 | UUID、来源约束、草稿/提交标识 |
| 前端统一离线检查 | 16/16 通过 | 含上述 3 个脚本，不重复累计；草稿 10 个、研究接口 6 个、来源导入 12 个浏览器用例及其他交互脚本 |
| 后端离线发现 | 276 项：174 通过、102 跳过 | 环境门控未启用的专项不计作通过 |
| 原生 PostgreSQL Agent/API | 23 项通过 | 专用数据库，迁移到 20261120_0007，alembic check 无漂移；结束后删除 |
| 真实本地端到端 | 通过 | 实际网络、数据库、独立进程及配置的模型，不以模拟结果代替 |

日志位于 `runtime/frontend-checks/`、`runtime/fix-integration-backend-tests.log`、`runtime/fix-integration-postgres-tests.log`。

## 真实链路证据

使用一个临时的已验证账号及一页合成验收 PDF。账号直接在隔离库准备；本轮不测试注册邮件投递。

- 实际浏览器登录、Cookie 会话、上传持久化、独立 Parser 解析就绪和 PDF 下载通过。
- 进入 PDF 后返回，新建研究的问题和论文选择仍然保留。
- 第一次创建请求真实提交给后端，然后人为丢弃响应；再次点击提交复用同一幂等键，返回同一任务，数据库仅有一个研究记录。
- 实际本地 Agent Worker 读取上传 PDF，调用已配置的 bailian / qwen3.8-27b 模型，返回中文答案和一条原文引用。
- 点击引用在页内打开对应 PDF 第 1 页，返回研究后保持同一条引用；未打开额外标签页。

```text
task_id: 363571eb-b1f3-4cff-801c-ece6a354d603
status: succeeded
stop_reason: completed
model_calls: 6
citations: 1
unresolved: []
model_errors: []
```

报告及截图：`runtime/live-integration/67c6b97202b242c192935465ee4d890b/`。结束后已关闭本次服务、删除临时数据库和文件；该任务 ID 仅用于验收日志追踪，不能在业务数据库中查询。既有账号、论文和任务未改动。

前一次真实模型调用返回 partial，严格完整验收没有放行；随后使用原文能够明确支持的单事实问题完成上述 completed 验收。这证明该链路可以完成，不能据此保证任意长篇、多论文或证据不足问题都会完整回答。

首次沙箱内运行出现模型连接错误，沙箱外连通检查和完整验收通过；未修改模型实现来绕过网络限制。

## 复跑命令

所有命令从仓库根目录运行。先按照 [前端说明](../frontend/README.md) 准备 Node 依赖、Python Playwright 和 Chromium。后端、Agent 依赖和 `agent/.env` 模型配置需已准备；后端配置指向本地 PostgreSQL，数据库账号需有创建、删除独立测试库的权限。

Windows PowerShell：

```powershell
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run verify:unit
& runtime/browser-venv/Scripts/python.exe -B frontend/checks/run-browser-checks.py
uv run --project backend --locked python -B backend/checks/live_research_acceptance.py --allow-model-requests
```

macOS / Linux：

```bash
npm --prefix frontend run build
npm --prefix frontend run verify:unit
runtime/browser-venv/bin/python -B frontend/checks/run-browser-checks.py
uv run --project backend --locked python -B backend/checks/live_research_acceptance.py --allow-model-requests
```

离线入口不需要业务 API 正在运行。真实入口自动创建独立数据库、临时账号、API、Parser Worker、Agent Worker、Vite 和 PDF，结束后清理；不会启动 Mail Worker，不投递邮件。`--allow-model-requests` 明确启用真实模型调用，可能产生少量费用。数据库与模型访问不可用时应保留失败结果，不改为模拟通过。

## 仍需独立验收

- 真实 arXiv 搜索、导入和外部引用下载受来源网络及额度影响。本轮只验证其离线前端流程，未新增真实 arXiv 请求。
- ECS 与 TACC 的 SSH/传输、调度、远程恢复及清理仍按 [Agent 传输验收](agent-transport-acceptance.md) 单独执行；本轮真实传输为 local。
- QQ 邮件注册、验证和找回密码的实际投递，以及长篇/多论文回答质量，不由这个一页合成资料的冒烟测试证明。
