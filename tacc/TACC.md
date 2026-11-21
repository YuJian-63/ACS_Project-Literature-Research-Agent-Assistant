# 在 TACC 上运行网页研究任务

网页把问题和可选的论文 UUID 发给后端。Worker 通过课程平台的 `tcloud` 提交一个 CPU 批作业。作业运行仓库中的 Baseline Agent，通过 HTTPS 读取用户论文库、调用百炼，然后把答案和引用写回 TACC 持久目录。Worker 下载结果并存入 PostgreSQL，网页可从引用打开原 PDF 对应页。[作业入口](research/run_job.py) · [Worker 传输](../backend/src/app/agent_bridge/tcloud.py)

## 本机后端怎样联调

1. 按[后端启动说明](../backend/README.md#1-首次启动)准备本机测试数据库、文件存储和可登录账号。从 `backend/` 执行 `uv sync --locked` 和 `uv run --locked alembic upgrade head`。API、论文库入口、Parser 和研究 Worker 共用这套数据库、存储和后端鉴权配置。
2. 在运行 Worker 的机器上初始化课程 SDK，运行 `tcloud env ls`。模板使用本账号的 `acs-network-probe`，其他账号可将模板的环境名改为自己可用的 Python 3.10+ 环境。作业首次运行会将 Python 3.12 和锁定依赖缓存到 `TACC_USERDIR/acs-research/runtime/`，后续作业从缓存解压到节点临时盘。[平台命令](README.md#常用-tcloud-命令) · [环境模板](research/tuxiv.conf) · [SDK 官方说明](https://github.com/turingaicloud/tcloud-sdk)
3. 用下列命令分别启动论文库入口和 Cloudflare Quick Tunnel。把隧道输出的 HTTPS 地址填入下方 Worker 配置，保持两个进程运行到结果返回。已有计算节点可访问的 HTTPS 后端时，直接填其地址。[论文库接口](../docs/api-contract.md#41-agent-论文库)

   ```sh
   # 在 backend/ 中运行
   uv run --locked uvicorn app.main:create_library_app --factory --host 127.0.0.1 --port 8001
   # 另开终端
   cloudflared tunnel --url http://127.0.0.1:8001
   ```

4. 在 `backend/.env` 设置以下变量。在指定的私有模型配置文件中填写 `MODEL_PROVIDER=bailian`、百炼的 `MODEL_BASE_URL`、账号可用的 `MODEL_NAME` 及 `BAILIAN_API_KEY`。macOS/Linux 上用 `chmod 600` 限制该文件权限。Worker 为每个作业向百炼申请临时 key，最长 30 分钟，并自动签发该任务的论文库只读令牌。用户登录网页即可提交。[模型配置示例](../agent/.env.example) · [百炼临时凭据](https://help.aliyun.com/zh/model-studio/generate-temporary-api-key)

   ```dotenv
   TASK_RUNNER=agent
   AGENT_DISPATCH_ENABLED=true
   AGENT_TRANSPORT=tcloud
   AGENT_POLL_SECONDS=30
   AGENT_LIBRARY_PUBLIC_URL=https://YOUR-TUNNEL.trycloudflare.com
   AGENT_TCLOUD_MODEL_ENV_FILE=/absolute/path/to/agent/.env
   ```

5. 从 `backend/` 在三个终端分别启动 API、Parser 和研究 Worker。从 `frontend/` 安装前端依赖并启动网页。

   ```sh
   uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
   uv run --locked python -m app.parser_worker
   uv run --locked python -m app.runner_worker
   ```

   ```sh
   npm ci
   npm run dev
   ```

## 从网页验证

打开 [本机网页](http://127.0.0.1:5173)，登录后在「论文库」上传一份 PDF。在「新建研究」先留空论文选择，按标题提问，并要求引用指定页的一项细节。得到答案后，点击正文引用，再点「查看 PDF 对应页」，核对论文、原文和页码。勾选同一篇论文再提交一次，可验证预选路径。任务内容由网页生成；[独立 Agent 的示例题](../agent/examples/library-qa.json)也可作为提问参考。

复现本次验收可上传[两页测试 PDF](<../frontend/checks/fixtures/Orchid Calibration Report.pdf>)，提问「只查我的论文库，《Orchid Calibration Report》最终校准记录的校验标签是什么？请引用第二页原文。」页面应给出 `LUMEN-472`，引用应能打开第二页。[浏览器验收脚本](../frontend/checks/live-tcloud.cjs)

每次提交仅同步 Baseline 所需源码、作业启动文件、任务清单和短期凭据。`input.zip` 只含 `manifest.json`、`task.json`、`sources.json`。预选论文随清单携带 UUID 与 SHA-256，动态检索按提交用户授权。两种路径都在作业首次读取时下载 PDF、核对摘要，沿用 Agent 的分页解析，无需向 `agent/data/` 复制文件。[Agent 读库实现](../agent/apis/library.py)

## 查看作业

`GET /api/v1/tasks/{task_id}` 中的 `agent.remote_job_id` 对应平台作业号，`agent.dispatch_id` 对应持久目录。可隔几分钟运行 `tcloud ps -j JOBID` 看队列。作业开始后会写 `status.json`，其中 `state=running` 表示执行中，`succeeded` 或 `failed` 表示已结束。队列为空时，以状态文件和网页结果为准。留足从 Worker 领取到作业结束的时间，含排队和首次环境安装。

```sh
tcloud cat slurm_log/acs-DISPATCH_ID-JOBID.log
tcloud download acs-research/jobs/DISPATCH_ID/status.json ./status.json
tcloud download acs-research/jobs/DISPATCH_ID/result.json ./result.json
```

### 本次验收与续跑

- **预选论文，已通过。** 2026-11-21，网页任务 `f2674517-7767-4fb8-a349-4ea86995bbdc` 由 Worker 自动派发为 CPU 作业 `30387`。Baseline 调用百炼 3 次，读到 `LUMEN-472`。网页点击引用打开了同一份 PDF 的第 2 页。随时可以在配置好 `tcloud` 的机器上查看已完成的状态和结果：

  ```sh
  tcloud cat acs-research/jobs/2f095c56-5307-4efb-94c2-eae4a2cab6d1/status.json
  tcloud download acs-research/jobs/2f095c56-5307-4efb-94c2-eae4a2cab6d1/result.json ./result-30387.json
  ```

- **空预选，待重试。** 第一次提交在 SDK 原有的 30 秒时限内未获回执，作业 `30391` 核对了本账号的 Slurm 历史，确认这次没有创建作业。预选任务的提交实际用了约 66 秒。Worker 现将提交等待单独设为 180 秒（`AGENT_TCLOUD_SUBMIT_TIMEOUT_SECONDS`）。恢复时按上文启动服务与新隧道，重新从网页提交一次空预选研究，核对 `search_library`、答案及第 2 页引用即可。上次的作业号只适用于预选任务。

更早的 CPU 作业 `30379` 已单独验证自动授权、按用户搜索、下载原文和跨账户隔离。[只读探测脚本](library-probe/submit.sh) · [课程 GPU 模型服务单独运行说明](qwen27b-student-release/README.md)
