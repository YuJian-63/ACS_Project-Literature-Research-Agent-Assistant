# 前端研究工作台

React、TypeScript 和 Vite 构建的论文研究界面，支持账号验证、论文管理、Agent 研究、原文引用和任务评估。界面默认英文，可切换中文；回答语言跟随研究问题。

## 本地开发

需要 Node.js `^20.19.0 || >=22.12.0`，以及已启动的后端 API、数据库和所需 Worker，见[后端启动说明](../backend/README.md)。在仓库根目录运行，PowerShell 可使用 `npm.cmd`：

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

访问 `http://127.0.0.1:5173`。需要覆盖配置时，将 [.env.example](.env.example) 复制为 `frontend/.env.local`：

| 配置 | 用途 |
| --- | --- |
| `VITE_API_BASE_URL` | 浏览器 API 来源，默认留空、使用同源 `/api`；独立来源不带 `/api` 后缀，并同步配置后端 CORS、前端来源和 Cookie。 |
| `API_PROXY_TARGET` | Vite 开发/预览代理目标，默认 `http://127.0.0.1:8000`，转发 `/api`、`/health`、`/ready`；生产使用服务器反向代理。 |

`VITE_*` 会进入浏览器，不能填写密钥。页面、路由和请求封装分别位于 [src/features](src/features/)、[src/app](src/app/)、[src/api](src/api/)；新增文案同步维护[中英文词条](src/i18n/messages.ts)。

## 使用流程

1. 登录并完成邮箱验证，上传 PDF 或搜索、导入 arXiv 论文，单份上限 **50 MB**。
2. 点击「新建研究」，填写问题，可预选最多 **20 篇**论文；不预选时可由 Agent 按需检索。提交后可在「研究记录」查看进度与结果。
3. 点击正文引用或「原文证据」查看证据，打开 PDF 对应页后可返回研究。外部 arXiv 来源需先导入对应版本。
4. 在「研究评估」查看五维评分、综合分、Agent 用量、模型性能、缓存 Token 和 GPU 快照；可主动申请或重试评分。

论文库支持页内阅读及单条、批量删除，被研究引用的论文受删除保护。账号支持找回、修改密码。

## 接口与指标

创建研究使用 `POST /api/v1/agent-research`，携带问题、论文 UUID 和 `allow_search`（默认 `true`）；相同提交重试复用 `Idempotency-Key`。详情使用 `GET /api/v1/agent-research/{task_id}`，指标在响应的 `metrics` 中。浏览器使用 Cookie 和 CSRF，不直接调用模型或 TACC。

问题与论文选择在当前标签页按账号隔离保存；提交成功、退出或会话失效后清理。[接口契约](../docs/api-contract.md) · [请求实现](src/api/agentResearch.ts)

研究或评分排队、执行期间每 30 秒刷新。缺失指标显示 `—`，真实零值正常展示，部分采集保留覆盖数量；GPU 为完成时快照。页面仅在用户操作时主动申请评分，报告按 `evaluation_id` 读取，评分用量与 Agent 用量分开展示。后端需完成迁移并运行评分 Worker，见[评分配置](../backend/README.md#deepseek-evaluation)和[指标口径](../backend/README.md#任务指标与前端接入)。

## 验证

在仓库根目录运行构建与单元检查：

```sh
npm --prefix frontend run build
npm --prefix frontend run verify:unit
```

离线浏览器检查使用模拟 API，无需真实后端或模型。在 Python 3.12 虚拟环境中安装 Playwright，将 `PLAYWRIGHT_BROWSERS_PATH` 设为仓库 `runtime/pw-browsers` 的绝对路径，再运行：

```sh
python -m pip install playwright
python -m playwright install chromium
python frontend/checks/run-browser-checks.py
```

入口自动启动 Vite，日志在 `runtime/frontend-checks/`；追加 `--only research-draft-browser.py` 可单独检查。真实集群、模型与引用验证见 [TACC 验收](../tacc/TACC.md)，可使用[两页测试论文](<checks/fixtures/Orchid Calibration Report.pdf>)。
