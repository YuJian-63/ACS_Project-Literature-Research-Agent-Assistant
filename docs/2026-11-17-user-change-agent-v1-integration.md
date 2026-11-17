# 用户改动：Agent v1 对接与运行记录

日期：2026-11-17。归属 user-change：用户发起，Codex 协助。
依据已确认的 [设计](superpowers/specs/2026-11-17-user-change-agent-v1-integration-design.md)
和 [计划](superpowers/plans/2026-11-17-user-change-agent-v1-integration.md)。历史记录不覆盖。

## 已实现

- 后端独立进程调用原有 `agent/baseline.py:run_task(task, persist=False)`，Agent 源码未修改。
- Agent 依赖与 Python 3.12 独立，后端不导入 Agent 的顶层 config/schemas/apis。
- 新输入不依赖本地论文和解析片段，支持 arXiv 固定来源和允许搜索。
- task_type 只作为后端 UI 分类；不向 Agent 传入 task_type 或旧 budget。
- 新 runner 为 agent，专用 Worker 负责领取、心跳、截止时间、停止清理和结果写入。
- 新 Alembic revision `20261117_0006` 保存 agent_input/agent_result；Agent 的 max_tokens 为 SQL NULL，
  表示不提供累计 Token 硬限制，保留旧任务有限预算规则。
- 保存 Agent 原生 Markdown 表格、引用字符串身份、物理页码、实际 usage、trace/configuration。
- completed/partial 保存为 succeeded，partial 明确展示未解决项；其他停止原因保存为 failed，
  仍可查询原生结果。通信/环境/格式失败则只有任务错误，结果可能为 null。
- 结果与 trace 查询均限制任务所属用户；列表不返回 trace，Agent 大结果列按需加载。
- 旧任务、旧结果渲染和 Worker 保留。此前旧研究流程的校验问题未在此次修改。

## 安装和启动

先准备 Agent 环境（在仓库根目录执行）：

```bash
cd agent
uv sync --frozen
# 首次配置才复制；已有 .env 不覆盖
cp .env.example .env
```

按 agent/README.md 配置模型；允许搜索还需相应搜索服务密钥。Neon 不参与此对接，
无需为了后端持久化设置 Agent 的 DATABASE_URL；persist 始终 false。
函数不会生成 CLI runs 文件，后端通过每次执行独立的临时结果文件接收完整 JSON。

后端环境和数据库仍按 backend/README.md 准备，然后：

```bash
cd backend
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

另开后端终端：

```bash
uv run --locked python -m app.agent_worker
```

默认使用 `<repo>/agent/.venv/bin/python`。如果使用其他 Python 3.12 环境，
在 backend/.env 设置绝对路径 `AGENT_PYTHON`。服务端路径，不允许前端指定。
桥接脚本检查 Python 版本；未配置可执行文件时提交返回 RUNNER_NOT_CONFIGURED。
如果依赖或模型配置有误，执行会失败而不会返回模拟成功。

前端启动后，在“新建研究”选择“Agent v1”，填写问题和 arXiv 来源，每行一项。
允许搜索时来源可以为空。默认主循环40步、执行600秒、单次输出4096 Token，
没有累计 Token 限制；前端不展示旧预算承诺。

若希望原有“论文库”创建流程也由 Agent 接管，设置 `TASK_RUNNER=agent`。
只有带 arXiv 来源的论文可转换；无需 ready chunks，本地上传 PDF 返回
AGENT_SOURCE_UNSUPPORTED。原有历史任务重试按已保存输入规则回放，不因切换 Runner 改变身份。
旧接口预算沿用 main 的自动预算语义（客户端预算不参与原有自动任务的身份）；
新 Agent 原生请求支持的执行参数则全部参与幂等哈希。

## API 增量

`POST /api/v1/tasks` 继续需要登录、Origin/CSRF 以及可选 Idempotency-Key：

```json
{
  "task_type": "qa",
  "question": "解释这篇论文的方法，并引用原文",
  "sources": ["1706.03762v7"],
  "allow_search": false,
  "max_papers": 3,
  "max_steps": 40,
  "timeout_seconds": 600,
  "max_output_tokens": 4096
}
```

服务端边界：问题最多8000字符；来源最多100项；max_papers=1—20、max_steps=1—100、
timeout_seconds=1—1800整数、max_output_tokens=1—32768。不同于 Agent 独立运行时，
后端不接受无限超时。这些是应用层上限，不是对 Agent 的功能修改。
后端生成 task_id，不允许用户覆盖。

- Task 详情新增 result_format=agent-v1、agent_input；budget.max_tokens 为 null。
- `GET /api/v1/tasks/{id}/agent-result`：原生 TaskResult 去掉 trace/configuration；
  尚无结果为 JSON null，失败任务也允许读取。旧任务返回409 RESULT_FORMAT_MISMATCH。
- `GET /api/v1/tasks/{id}/agent-trace`：{trace,configuration}；尚无结果为空数组/对象。
  常见凭据字段名脱敏，字段名过滤不等同于任意文本内容的秘密检测，不应把密钥注入提示词。
- 原有 /events 查询继续可用；Agent 未提供执行中 trace 回调，只有结束时完整 trace。
- 前端结果保留原始引用身份，不将其转换成本地 PaperChunk UUID；原始 URL 仅允许 http/https 展示。

## 验证过程

- 新增输入、生命周期及 HTTP 测试；覆盖来源、幂等、用户隔离、部分完成、失败结果、
  迟到/跨任务结果、空 usage、Worker调用、trace分离等。
- 进程测试覆盖完整 JSON、task_id不匹配、异常/无效输出、输出限制、超时、取消、
  后代进程停止与临时文件清理。
- 使用 Agent 原有 uv.lock 在 `/private/tmp/agent-v1-env` 建立 Python3.12 锁定环境；
  实际调用真实 run_task 和真实桥接，注入离线模型/读取器，成功返回引用、usage和trace。
- Agent 自带测试：65通过、1跳过；前端 typecheck、生产构建和新旧契约检查通过。
- 原生 PostgreSQL17.11 隔离私有 socket 数据库完成初始到0006迁移、alembic check、
  幂等/归属/结果/降级保护、真实会话与CSRF HTTP提交→Worker→结果查询验证。
  Worker在该HTTP测试中注入离线结果函数；真实 Agent 离线桥接另行独立验证。
- 原生测试发现并修复 SQLAlchemy None 被8000默认值覆盖的问题（evaluates_none），
  SQLite不能代表这个约束行为。
- 独立审查发现并修复切换Runner时旧请求先转换导致重试失败的问题，补充 RED→GREEN 回归。

## 验收边界

未调用真实模型、搜索或 arXiv 服务，不声称真实生成质量或联网链路已经验收。
没有迁移用户现有数据库，测试使用临时隔离数据库。完整测试结果在最终验证后追加。
没有修改 Agent 源码；没有自动提交或推送 Git。

## 最终验证追加

- 后端完整 pytest：149 passed、62 skipped、62 subtests passed（包含实际执行的新增
  原生 PostgreSQL 和 Python3.12 Agent离线桥接；62项旧数据库专项因未配置各自测试库跳过）。
- Agent 锁定环境自带 pytest：65 passed、1 skipped。
- 前端 TypeScript 两套配置检查、Vite生产构建、新Agent契约检查通过；原有review检查通过，
  检查时可选HMR websocket因沙箱端口限制报错，不影响断言和退出码。
- 新代码静态未定义/语法检查和 git diff 空白检查通过；迁移 head为20261117_0006。
- 第三方依赖有弃用提示，没有修改依赖代码。
- 作者自查之外，独立审查覆盖后端、进程、迁移和前端；发现的主要幂等问题已用回归测试修复。
- 此次新增实现尚未进行浏览器交互验收；没有把构建或离线验证描述成真实模型端到端验收。
- 当前进程组清理和资源限制面向macOS/Linux；Windows运行此进程桥接需另行适配。

### 执行中的决定

1. 旧paper_ids请求继续使用main既有自动预算身份规则，客户端旧budget差异不产生新冲突；
   代价是旧budget仍不控制Agent。新原生输入明确暴露并哈希实际支持的执行参数。
2. 独立环境安装在临时目录供验收，未将个人机器路径或密钥写入仓库；
   日常启动需要按本记录建立agent/.venv或配置AGENT_PYTHON。
3. trace只对本人独立查询，常见字段名脱敏；脱敏不保证识别模型文本中任意秘密。

## 用户要求提交前的复核追加

2026-11-17，用户要求将Agent对接提交到backend-dev。
按要求，本地测试服务和测试数据库此前已停止并清理；个人.env保留且不纳入Git。
此次未重新启动服务或创建数据库。最新复核：后端148 passed、63 skipped、
62 subtests passed；其中新增PostgreSQL专项因临时测试库已清理而跳过，之前执行通过的
证据保留在上文，不把本次跳过描述为重新验收通过。真实Agent离线桥接本次复跑通过。
前端TypeScript检查、生产构建、Agent契约检查、Git空白检查通过。
此前“没有自动提交或推送”的描述为当时状态；本次依据用户明确要求提交并推送。
