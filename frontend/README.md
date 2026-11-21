# 前端研究工作台

登录工作台后，可以上传或导入论文，提交研究问题，并从答案中的引用打开 PDF 原文。前端使用 React、TypeScript 和 Vite。

## 从论文到研究结果

1. 在「论文库」点击「选择 PDF」或拖入文件，每次一篇，单份上限 50 MB。「搜索论文」可按关键词查找 arXiv 论文并导入库中。
2. 点击「新建研究」，填写问题。若要指定论文，在「参考论文（可选）」勾选最多 20 篇，也可以先在论文库勾选再进入研究页。若要让 Agent 自行查库，留空参考论文，在问题里写出标题或关键词。
3. 点击「开始研究」。页面会自动打开研究结果并刷新状态。提交后可以关页，稍后从「研究记录」重新打开。
4. 在「研究正文」点击引用编号，或在「引用与来源」选择原文证据。在「证据与来源」中点击「查看 PDF 对应页」打开库内原件，点击「返回研究」回到同一条引用。外部 arXiv 来源会先提示导入对应版本。

论文库支持页内阅读、切换论文和单条或批量删除。已被研究引用的论文受删除保护。右上角可切换中英文界面，回答语言跟随研究问题。账号支持邮箱验证、找回和修改密码。

## 提交的数据和凭据

上传 PDF 时，后端将原件保存到当前账号的论文库。创建研究时，网页向 `POST /api/v1/agent-research` 发送问题、论文 UUID 列表和 `allow_search: true`。预选论文与运行中检索到的论文都可通过引用回到库内原件。

浏览器使用登录 Cookie 和 CSRF 令牌。Worker 为 TACC 作业准备 Agent 源码和任务清单，签发论文库只读凭据并获取临时模型凭据。作业按需下载 PDF，Worker 取回结果后，网页通过 `GET /api/v1/agent-research/{task_id}` 展示。部署步骤和两种提交方式的真实验收见 [TACC 操作指南](../tacc/TACC.md)。

问题和论文选择暂存在当前标签页，按账号隔离。未确认提交的相同输入复用同一幂等键。提交成功、退出或会话失效会清理草稿。[研究请求实现](src/api/agentResearch.ts) · [后端 API 契约](../docs/api-contract.md)

## 本地开发

要求 Node.js `^20.19.0 || >=22.12.0`。从仓库根目录运行，Windows PowerShell 可将 `npm` 写为 `npm.cmd`。

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

打开[本地工作台](http://127.0.0.1:5173)。Vite 默认将 `/api`、`/health`、`/ready` 转发到 `http://127.0.0.1:8000`，可用 `API_PROXY_TARGET` 指定开发代理目标。跨域部署需配置 `VITE_API_BASE_URL`、后端 CORS、`FRONTEND_PUBLIC_URL` 和会话 Cookie。研究执行需要运行后端 API、数据库和研究 Worker。[后端启动说明](../backend/README.md)

页面源代码按功能放在 [src/features](src/features)，路由在 [src/app](src/app)，HTTP 客户端在 [src/api](src/api)。新增界面文案请同步维护[中英文词条](src/i18n/messages.ts)。

## 回归检查

从仓库根目录执行构建和单元检查。

```sh
npm --prefix frontend run build
npm --prefix frontend run verify:unit
```

**离线浏览器回归**使用 API 夹具覆盖研究提交、草稿恢复、引用往返、来源导入及论文库操作。安装上述前端依赖后，在 Python 3.12 虚拟环境中安装 `playwright`，将 `PLAYWRIGHT_BROWSERS_PATH` 设为仓库中 `runtime/pw-browsers` 的绝对路径，然后安装 Chromium 并运行检查。

```sh
python -m playwright install chromium
python frontend/checks/run-browser-checks.py
```

入口会启动 Vite，日志写入 `runtime/frontend-checks/`。可用 `--only research-draft-browser.py` 只运行指定检查。验证真实课程集群、百炼和原文引用时，使用 [TACC 网页验收流程](../tacc/TACC.md)及[两页测试论文](<checks/fixtures/Orchid Calibration Report.pdf>)。
