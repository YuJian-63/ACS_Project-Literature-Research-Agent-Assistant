> 当前 v3 使用统一研究页面，问题必填、论文可选；不显示旧三类研究流程。本文旧流程说明仅作历史参考，当前合并情况见 [v3 合并说明](../docs/v3-main-merge-resolution.md)。

# 前端研究工作台

React + TypeScript + Vite 单页应用，使用 Ant Design、Axios、React Router 和 React Markdown。当前页面使用统一研究接口 `/api/v1/agent-research`，由后端派发给 Agent；旧摘要、问答、综述专用页面已被统一研究流程替代。

## 目录

```text
src/
├── main.tsx
├── app/                         # 路由、工作台布局、全局样式
├── api/                         # HTTP、账号、论文及统一研究接口
├── features/
│   ├── auth/                    # 注册、登录、找回密码、会话和账号设置
│   ├── papers/                  # 论文库、上传、选择和页内 PDF 阅读
│   ├── search/                  # arXiv 搜索和导入
│   └── agentResearch/           # 新建研究、历史、结果和来源导入
├── shared/
│   ├── components/              # 页头、错误、分页、语言和状态
│   ├── hooks/                   # 通用资源请求和响应式视口
│   └── lib/                     # 阅读导航、UUID、账号研究草稿
├── i18n/                        # 中英文文案和语言状态
└── assets/                      # 本地字体和许可证
checks/                          # 当前接口对应的离线检查与真实联调浏览器流程
```

组件和业务逻辑优先放在对应 feature，跨模块工具放入 shared。共享层不导入业务组件。页面按路由懒加载，搜索页在站内切换时保留状态。

## 启动

要求 Node.js `^20.19.0 || >=22.12.0`。所有命令均从仓库根目录运行。

Windows PowerShell：

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run dev
```

macOS / Linux：

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

打开 `http://127.0.0.1:5175`。后端、数据库、Parser Worker 和 Agent Worker 的启动步骤见 `../docs/terminal-operations.md`、`../backend/README.md`。前端不会启动后端或生成示例结果。只有 API 没有 Worker 时，任务可能一直排队。

默认代理 `/api`、`/health`、`/ready` 到 `http://127.0.0.1:8002`，可用 `API_PROXY_TARGET` 修改。跨域部署还需配置 `VITE_API_BASE_URL`、后端允许的 CORS Origin、`FRONTEND_PUBLIC_URL` 和 Cookie 设置；不得将模型、邮件或数据库密钥写入前端环境变量。

## 账号和接口

账号通过邮箱验证后，以用户名和密码登录；支持找回密码和修改密码。私有请求携带 Cookie，写请求自动附带 `X-CSRF-Token`。退出或会话失效会取消旧请求并清理当前标签页研究草稿；其他标签页收到账号事件后也会清理。

| 页面或操作 | API |
| --- | --- |
| 注册、验证、登录、找回和改密 | `/api/v1/auth/*` |
| 论文列表、上传 | `GET/POST /api/v1/papers` |
| 论文详情、删除 | `GET/DELETE /api/v1/papers/{id}` |
| 下载 PDF | `GET /api/v1/papers/{id}/file` |
| 搜索论文 | `GET /api/v1/paper-search` |
| 创建及查看导入、失败重试 | `/api/v1/paper-imports`、`/{id}`、`/{id}/retry` |
| 新建研究、研究记录 | `POST/GET /api/v1/agent-research` |
| 研究详情、删除记录 | `GET/DELETE /api/v1/agent-research/{task_id}` |

字段和错误码以 `../docs/api-contract.md` 为准。V3 页面不请求旧 `/tasks`、artifacts 或 events 来展示统一研究结果。

## 研究提交和草稿

研究问题必填，可指定最多 20 篇论文；也可不选论文，由 Agent 查找资料。前端只提交 `question`、`paper_ids`、`allow_search`，不提供预算设置，也不将界面语言写入任务。回答语言由后端根据问题内容确定。

每次研究提交携带随机 `Idempotency-Key`。同一输入在响应丢失、失败重试或刷新后复用未确认提交的键；问题、论文选择或搜索设置改变后，下一次提交使用新键。成功取得任务 ID 后清理该次草稿和键，之后主动创建同样的问题属于新任务。

问题、所选论文 ID、预选参数来源和未确认提交保存在当前标签页的 `sessionStorage`，以账号 ID 隔离。打开 PDF 后返回、刷新或站内跳转可恢复。恢复时重新请求论文详情，已删除或不再可用的草稿论文会被移除并提示。明确的新预选参数可替换草稿选择，同一入口返回时保留用户后来修改的选择。成功提交、退出和会话失效清理草稿；存储被禁用时页面仍可使用，同一页面内的重试仍复用键，但不能保证刷新恢复。

## 阅读、搜索和研究结果

- 论文标题在当前页面打开 PDF，支持切换、专注阅读、错误重试和新标签页备用入口。关闭及切换文件会释放旧 Blob URL。
- 搜索支持排序、每页 10/25/50 篇、页码跳转、翻页后回到结果顶部和摘要展开。搜索失败显示通知并清空当前搜索，用户可重新输入后提交；不会自动反复请求 arXiv。
- 导入状态和 PDF 解析状态分别展示；下载成功不等于解析完成。重试导入携带 `expected_attempt`，避免并发重复重试。
- 研究详情轮询统一研究接口，显示排队、执行、失败和结果。部分完成保留已有正文、比较、引用和待解决问题。查询失败可手动重连。
- 点击引用打开证据抽屉，跳转 PDF 时保留引用页码和返回任务信息；返回后恢复该条引用。
- 外部 arXiv 来源先确认导入，等待下载、解析完成后再进入本地 UUID 阅读器。仅导入来源明确指定的版本；缺少版本、摘要/版本不匹配或页码越界会提示，不擅自使用最新版本。停止等待不取消后台导入。
- 论文和研究记录支持单条、跨页批量删除，后端执行用户归属、任务引用和运行状态保护。部分删除失败会汇总原因并保留失败项勾选。

## 中英文界面

右上角切换中文和 English，偏好键为 `literature-v3-ui-locale`。界面切换不改写问题、论文原文或模型结果，也不改变未确认提交的幂等键。新增文案需同步维护 `src/i18n/messages.ts`。

## 类型检查和单元检查

Windows 使用 `npm.cmd`，macOS / Linux 使用 `npm`：

```powershell
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run verify:unit
```

`build` 包含 TypeScript 检查。`verify:unit` 覆盖 UUID、来源版本/页码约束、提交标识、草稿隔离、异常存储和定向清理。

## 离线浏览器回归

首次准备 Python Playwright 环境。Windows PowerShell：

```powershell
uv venv runtime/browser-venv --python 3.12
uv pip install --python runtime/browser-venv/Scripts/python.exe playwright
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) 'runtime/pw-browsers'
& runtime/browser-venv/Scripts/python.exe -m playwright install chromium
& runtime/browser-venv/Scripts/python.exe -B frontend/checks/run-browser-checks.py
```

macOS / Linux：

```bash
uv venv runtime/browser-venv --python 3.12
uv pip install --python runtime/browser-venv/bin/python playwright
export PLAYWRIGHT_BROWSERS_PATH="$(pwd)/runtime/pw-browsers"
runtime/browser-venv/bin/python -m playwright install chromium
runtime/browser-venv/bin/python -B frontend/checks/run-browser-checks.py
```

已有环境时直接运行最后一行。入口自动启动独立 Vite，执行当前所有离线检查并关闭自己启动的服务；日志位于 `runtime/frontend-checks/`。可传 `--url http://127.0.0.1:5175` 复用已有 Vite，或用 `--only research-draft-browser.py` 仅检查指定脚本。

所有离线 API 都由夹具拦截，不连接数据库、arXiv、邮件或真实模型。Python 与 Node 检查默认使用 Playwright Chromium，不再硬编码 macOS Chrome 路径。Node 检查的 Playwright 模块位置由统一入口自动提供；可通过 `PLAYWRIGHT_MODULE` 覆盖。

| 脚本 | 覆盖范围 |
| --- | --- |
| `agent-integration-browser.py` | 当前研究 API、原生结果、语言、部分完成、引用往返和 HTTP 登录 |
| `research-draft-browser.py` | 幂等重试、刷新、PDF 往返、预选参数、账号隔离和草稿清理 |
| `research-source-import-browser.py` | 外部来源导入、复用、重试、解析等待和版本/页码保护 |
| `agent-*-browser.cjs` | 新建研究、可选论文、记录页面和移动端 |
| `library-reader-browser.py` | 阅读器、文件重试、跨页选择、焦点、失效会话和双语布局 |
| `library-*-browser.cjs` | 单条、批量删除及部分失败 |
| `search-browser.py` | 搜索、排序、分页、摘要展开和双语布局 |
| `search-*-browser.cjs` | 搜索状态保持、通知、错误恢复和导入 |
| `sidebar-browser.cjs` | 侧栏切换、持久化及键盘和移动端操作 |

真实浏览器/API/Agent 联调与这些离线检查分开执行，不能用离线通过代替真实模型或 ECS/TACC 互通验收。

真实联调入口和最新结果见 `../docs/frontend-backend-acceptance.md`。本地验收脚本使用独立数据库、临时账号及合成 PDF，实际执行 Parser、Agent Worker 和配置的模型。
