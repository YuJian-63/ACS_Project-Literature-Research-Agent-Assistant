> 更新：main 的统一研究接口与执行适配代码现已合入，迁移新增 v3_0002；本文早期“未对接”描述以 [最新合并说明](v3-main-merge-resolution.md) 为准。

# v3 独立版本交接说明

本说明替代此前“复用旧数据库与模拟后端”的方案。用户已确认：保留当前 v3 界面、登录、搜索和论文库；删除旧三类研究流程与模拟对接残留，从独立空库继续开发。

## 1. 当前隔离结果

| 项目 | v3 当前配置 |
| --- | --- |
| Git 工作目录 / 分支 | `ACS_Project-Literature-Research-Agent-Assistant-v3` / `frontend-dev-v3` |
| 前端地址 | http://127.0.0.1:5175 |
| 后端地址 | http://127.0.0.1:8002 |
| 数据库实例 | 容器 `literature-v3-postgres-1`，端口 55435 |
| 数据卷 | `literature_v3_postgres_data` |
| 数据库 / 账号 | `literature_v3` / `literature_v3`，独立随机密码 |
| 初始迁移 | `backend/alembic_v3/versions/v3_0001_initial_isolated_v3_schema.py` |
| PDF 存储 | `backend/runtime/v3/storage` |
| 本地会话 Cookie | `lra_v3_session` |
| Python 环境 | v3 自己的 `backend/.venv` |
| 私有配置 | v3 自己的 `backend/.env`、`frontend/.env.local`，不提交 Git |

新库从空数据开始：没有旧账号、会话、论文、解析文本或研究记录。只预置 arXiv 调度 gate 和迁移版本。需要在 v3 重新注册、上传或导入论文。

旧数据库实例、文件及 v2 代码没有被重置、迁移或删除。Git worktree 仍正常共用版本历史，但运行配置、数据库、文件和会话不再共用。原来另一份本地数据库也没有被复用为新 v3。

按用户选择，仅将邮件和 arXiv 的服务配置复制成 v3 的独立副本。v3 启动不再读取 v2 配置；数据库密码、Cookie、CSRF/限流密钥、发件箱加密密钥均独立生成。两个版本可以使用同一邮箱服务，但账号表和发件箱不共享。

## 2. 保留的界面与功能

- 登录、注册验证、找回/修改密码、独立会话。
- arXiv 搜索、结果分页与导入提示。
- PDF 上传、论文库、解析/导入状态、页内 PDF 阅读、单篇和批量删除。
- 统一新建研究：问题必填，参考论文可选 0—20 篇，默认允许搜索；没有步骤编号和旧类别。
- 统一研究记录：问题、论文标题/阅读链接、状态、资料数量、创建时间、查看与删除；没有类型筛选。
- 统一结果页：按返回内容显示正文、比较表、待解决问题和引用/来源；没有示例选择器或自动假结果。
- 中文／EN 文案、表头居中/正文左对齐、3 秒通知等已确认的 v3 设置。

浏览器语言、侧栏偏好与跨标签页认证通知也使用 v3 命名空间。PDF 的研究返回链接使用新的研究 ID／引用标识，不再依赖旧 artifact、任务类别或 read/compare 参数。

## 3. 已清理的旧内容

- 旧摘要、问答、跨论文综述的表单和详情页。
- 旧 Artifact、Comparison、Evidence 等被新统一结果组件替代的页面组件；保留并迁移仍在使用的原文整理、执行中提示。
- 旧 TaskType、任务创建/事件/产物客户端接口及无用翻译。
- 独立虚构预览 HTML、prototype 数据与样式依赖；正式研究样式已迁入 `features/agentResearch/research.css`。
- 后端旧 Task／TaskPaper／TaskEvent／Artifact／Citation 模型、API、工作流、预算与执行器、Mock/LLM Worker。
- LangGraph 及旧执行器不再需要的后端依赖；v3 锁文件和虚拟环境已独立同步。
- SQLite 模拟结果 API、存储、导入/启动脚本、四条模拟记录及其 JSON 导入源。
- 不再适用的旧迁移、SQL、重置工具和旧研究测试；保留账号/搜索测试，并新增独立结构与真实 PostgreSQL 流程测试。

这些清理发生在 v3 工作目录，v2 保留原代码。清理前已保存一份权限受限的本机检查点，未上传旧账号、论文、结果或密钥。

`agent/` 独立 Agent 源码没有改动或删除，供后续正式接入。

## 4. 后端现在是什么状态

不再使用模拟存储，研究记录基础 API 直接连接 v3 自己的 PostgreSQL：

| 接口 | 当前行为 |
| --- | --- |
| `GET /api/v1/agent-research` | 用户隔离的分页列表；空库返回空列表 |
| `GET /api/v1/agent-research/{UUID}` | 读取自己的统一研究及结果；没有记录返回 404 |
| `DELETE /api/v1/agent-research/{UUID}` | 删除自己的记录；运行中返回 409；级联释放论文引用 |
| `POST /api/v1/agent-research` | 校验请求后返回 `503 AGENT_NOT_CONNECTED`，不产生假任务 |

**真实 Agent 自动执行仍未接入。** “开始研究”不会回退调用旧 LLM 流程，未来应直接接 Agent。

新结构只有一类研究，使用 `agent_research`、`research_papers`；没有 `task_type`，没有旧 tasks/artifacts 等表。论文引用通过用户复合外键约束，研究引用未释放时禁止删除论文。

账号、论文、来源/导入、Parser/Import/Mail Worker 保留，但共用的租约/时钟工具已从旧 tasks 模块抽出到 `app/db/leases.py`。

## 5. 正式 Agent 对接的契约与待办

创建请求：

```json
{
  "question": "已有证据如何支持这个结论？",
  "paper_ids": [],
  "allow_search": true
}
```

问题最长 8000 字符，不能为空白；论文列表可省略或为空，最多 20 个本地 UUID。没有论文且关闭搜索时拒绝输入。

正式执行接通后，创建成功应返回 `{"task_id":"研究UUID"}`，前端跳转 `/tasks/:taskId`。当前 POST 尚未返回成功。

列表响应使用 `{items,total,limit,offset}`，条目字段是 `id,question,status,paper_ids,papers,created_at`。`papers` 的条目为 `{id,title}`。

详情使用生命周期外壳：

```json
{
  "task_id": "研究UUID",
  "question": "已有证据如何支持这个结论？",
  "status": "running",
  "paper_ids": [],
  "result": null,
  "error": null
}
```

生命周期为 `queued/running/succeeded/failed`。运行状态按 2 秒轮询；读取失败提供刷新。没有可用真实进度时不显示伪造百分比。

`result` 接收 Agent 的结构化内容：`answer`、Markdown 字符串形式的 `comparison_table`、`citations`、`sources`、`unresolved`、`stop_reason` 等。空字符串/空数组表示无内容；不要用裸 `TaskResult` 替代详情外壳。

证据需要 `chunk_id,source_id,paper_id,page,source_text,title,url`，可选 `version`。正文用 `[chunk_id]`，页面匹配并转为 `[C1]`。`page` 为从 1 开始的 PDF 物理页码。外部来源必须映射为可阅读的本地论文 UUID，不能直接把 arXiv ID 当作阅读器的本地 ID。

后续需要实现：

1. 根据问题优先检索用户可访问的已有资料，证据不足时搜索补充论文。
2. 将可选本地论文 ID、上传 PDF 和解析原文适配为 Agent 可使用的 `sources`／工具输入。
3. 统一研究的真实调度、状态更新、超时、幂等和部分结果规则。
4. 对 Agent 结果结构及原文引用进行在线校验与正式持久化。
5. 搜索所得论文的导入、解析、来源追溯及本地阅读 ID 映射。
6. 保持全链路用户隔离及删除后引用释放。
7. 明确 Agent `max_papers` 默认 3 与界面最多 20 篇的关系，避免截断指定论文。

研究执行尚未实现，不应将当前页面完善理解为后端 Agent 调度已经完成。

## 6. 独立启动

首次安装可从 v3 项目根目录生成自己的配置：

```bash
python3 backend/scripts/init_local_env.py
```

脚本只使用当前项目模板，生成新密码/密钥，拒绝覆盖已有 `.env`。然后在 `backend/` 中：

```bash
uv sync --frozen
docker compose up -d --wait
uv run alembic upgrade head
uv run alembic check
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8002
```

按功能在单独终端启动：

```bash
uv run python -m app.parser_worker
uv run python -m app.import_worker
uv run python -m app.mail_worker
```

前端在 `frontend/`：

```bash
npm ci
npm run dev
```

打开 http://127.0.0.1:5175 。前端默认代理 8002，无需其他版本的服务。来源校验、邮件链接与浏览器地址应使用同一主机名。

不要再使用旧模拟后端启动/导入命令，不要把代理指回旧后端，也不要把数据库或存储路径指回其他版本。

## 7. 防误接与数据边界

- 数据库名只允许 `literature_v3` 或 `literature_v3_test_*`。
- 拒绝 URL query 中可覆盖目标的 `dbname/database/service/host/hostaddr/port/user` 等参数。
- 默认存储也使用 `runtime/v3/storage`，不会因漏配回退旧目录。
- 只在新的 PostgreSQL 实例创建新迁移和测试库，不对旧数据库执行迁移或 reset。
- 本次没有复制旧账号、会话、PDF、chunks 或研究结果。
- 本地配置、Docker 数据卷、PDF、测试数据及检查点不上传 Git。

## 8. 验证

已通过独立初始迁移和 `alembic check`、前端类型检查/构建、输入和隔离回归，以及真实 PostgreSQL 的账号/论文/引用流程检查。认证检查在临时独立测试库运行；不向真实邮箱发送测试邮件。搜索/导入的外部来源在测试中使用替代实现，不向 arXiv 发测试请求。

最终验证：90 项测试被发现（未提供临时库时有 34 项按设计跳过），75 项原生 PostgreSQL 认证检查全部通过；临时 PostgreSQL 的综合业务流程、三组拦截接口的浏览器检查、真实登录页/代理/旧 Cookie 拒绝检查均通过。所有临时测试库已清理，实际 v3 业务库保持为空，等待用户重新注册和导入资料。

验收时还只读核对了 v2：账号、论文与原研究记录仍存在，8 个原 PDF 的大小和 SHA256 与数据库一致；原 v2 工作目录干净，原 Python 依赖和旧 API 仍可加载。没有把这些数据导入 v3。

## 9. 上传状态

本版通过 `frontend-dev-v3` 分支交付，提交说明使用英文。上传范围为源码、独立迁移、依赖锁文件、检查脚本和交接说明；本机 `.env`、存储、数据库、备份和旧测试结果不随代码上传。
