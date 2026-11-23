# 后端数据库设计

后端使用 PostgreSQL 17、SQLAlchemy 和 Alembic，当前迁移 head 为 `20261123_0016`。以下概述全部 21 张业务表；完整字段、外键和索引见 [业务模型](../backend/src/app/db/models.py)、[账号模型](../backend/src/app/db/accounts.py)及 [DDL](../backend/sql/schema.sql)。

实体 ID 主要使用 UUID，时间使用带时区时间戳，配置、原生结果和评分快照使用 JSONB。原始 PDF 位于 `STORAGE_ROOT/uploads/<paper_id>.pdf`；备份与还原须同时保留数据库和存储目录。

## 账号与权限

| 表 | 用途 |
| --- | --- |
| `users` | 用户名、邮箱及其唯一规范化键、密码哈希、账号状态与 `auth_version`。启用账号须已验证邮箱。 |
| `auth_sessions` | 会话令牌哈希、用户、认证版本、到期及撤销时间。 |
| `auth_email_tokens` | 邮箱验证和密码重置令牌哈希、用途、有效期及消费状态。 |
| `auth_mail_outbox` | 加密邮件载荷、投递状态、重试时间及 Worker 租约。 |
| `auth_rate_buckets` | 登录、注册和邮件申请等操作的限流计数。 |

用户名和邮箱以小写键查重；登录仍要求用户名大小写与注册值一致。API 从会话确定用户。`papers`、`tasks`、`paper_sources`、`paper_imports` 均保存 `user_id`，任务—论文、来源/导入—论文使用复合外键防止跨用户关联；读取时仍校验归属。

## 论文库与 arXiv 导入

| 表 | 用途 |
| --- | --- |
| `papers` | 用户、标题、原文件名、存储路径、大小、SHA-256、物理页数、解析状态及租约。单份上限 52,428,800 字节，界面标为 50 MB。 |
| `paper_sources` | 已导入的来源元数据，`(user_id, provider, external_id)` 唯一，arXiv ID 必须带版本。 |
| `paper_imports` | 下载作业、尝试轮次、租约、已核验元数据及成功后的论文 ID；同用户同来源版本复用记录。 |
| `source_request_gates` | 多进程共享的 arXiv 请求节流、持有者及上游等待时间。 |
| `paper_chunks` | 早期分页文本片段，仅供历史引用按原片段 ID 读取。 |

Parser 将论文从 `uploaded → processing → ready / failed`，提取页数并尝试补齐标题，不再生成研究分块。新研究由独立 Agent 读取、分块；外部 arXiv 来源保存在原生结果中，用户导入对应版本后才建立本地论文。

## 研究任务、结果与引用

| 表 | 用途 |
| --- | --- |
| `tasks` | 问题、运行器、冻结配置与预算、状态、Worker 租约、使用量及错误。新任务只使用 Agent，旧运行器字段供历史读取。 |
| `course_service` | 全站课程 GPU 服务的启动者、轮次 `generation`、作业号、地址及状态。 |
| `shared_model_endpoints` | 以 `user_id` 为主键保存用户设置的课程内网模型地址。 |
| `agent_queue_settings` | 全站研究并发上限，默认 2，范围 1–4。 |
| `agent_runs` | 以 `task_id` 为主键保存派发清单、唯一 `dispatch_id`、输入摘要、平台作业号、停止原因及原生 `result`。 |
| `task_papers` | 以 `(task_id, paper_id)` 为主键关联库内论文，并用 `(paper_id, paper_sha256)` 固定原件。 |
| `task_events` | 以 `(task_id, seq)` 保存有序事件，序号与 `tasks.last_event_seq` 同事务更新。 |
| `artifacts` | 每任务至多一份可展示产物，包含 Markdown 和兼容比较表字段。 |
| `citations` | 产物的库内引用：引用键、论文、物理页及原文；新引用使用 Agent 来源/片段标识，旧引用通过 `chunk_id` 关联历史片段。 |

`task_papers.selection_order` 非空时表示用户预选顺序（0–19，同任务唯一）；为空时表示 Agent 运行中发现的库内论文。结果入库须核验归属、SHA-256 和引用页码；预选列表只读取非空顺序，发现的论文仍可通过引用打开。

任务状态为 `queued/running/succeeded/failed`；Agent 的 `completed/partial` 均保存可读产物并映射为 `succeeded`，其余停止原因映射为失败。删除任务级联删除执行记录、关联、事件、产物、引用及评分。论文被任务关联时不可删除或更改原件摘要；删除无关联论文时，API 一并清理来源、关联的导入记录及 PDF。

## 异步评分与每日额度

| 表 | 用途 |
| --- | --- |
| `task_evaluations` | 评分版本、输入/配置/证据快照、报告、用量、错误及租约；`(task_id, input_sha256, config_sha256, revision)` 唯一，修订号从 0 开始。显式重评新增修订，保留旧报告及尝试记录。 |
| `evaluation_daily_quotas` | 以 `(user_id, day)` 为主键，按 UTC 日原子预留新评分版本额度。复用、重试已预留额度的同版本不重复计数，删除任务不退还。 |

启用评分后，结果入库自动排队；历史结果可主动申请。评分状态为 `pending/running/succeeded/failed/skipped`，独立于研究状态。研究每日额度直接统计当日现存任务，删除可能降低计数；评分额度有独立记录。Agent 和模型服务指标从原生结果整理，不另建表。[指标与评分接口](api-contract.md#8-任务指标与评分)

## 提交、租约与回传

1. **提交：** 同事务写入任务、执行记录、预选关联和首条事件。幂等键对同一用户唯一；同键同输入复用任务，不同输入返回冲突。
2. **执行：** 研究 Worker 锁定全站队列配置和候选任务，优先恢复已派发作业；以 `worker_id` 和 `lease_expires_at` 续租。远程操作在事务外执行，截止时间从首次领取起算；租约过期且未超时可沿用派发标识重新入队。
3. **回传：** 有效租约持有者核对派发标识、输入摘要、任务身份和引用来源后，同事务保存原生结果、产物、引用及终态。[任务生命周期](../backend/src/app/tasks/lifecycle.py) · [结果入库](../backend/src/app/agent_bridge/store.py)

按用户、状态和创建时间的索引支持列表查询，队列及到期租约使用专用索引；原生结果和证据保留在 JSONB 中，不作为全文或向量检索库。

## 数据库迁移

在 `backend/` 运行 `uv run --locked alembic upgrade head`，再检查 `alembic current` 与 `alembic heads` 一致、`alembic check` 无结构差异。[迁移文件](../backend/alembic/versions) · [备份与维护](../backend/README.md#4-迁移维护)

关键边界：`0007` 引入 Agent 执行记录；`0008` 将 PDF 上限改为 50 MB；`0009` 允许发现论文的顺序为空，存在此类关联时不能直接退回 `0008`；`0014` 增加评分与配额；`0015` 将任务步数约束提高到 200，存在超过 100 步的任务时不能直接降级至 `0014`；`0016` 增加评分修订号，存在同任务、输入及配置的多个修订时拒绝降级，避免丢失历史报告。

<a id="114-0004-升级重置与回退边界"></a>

### 从旧匿名库升级

`20261114_0004` 遇到已有 `papers/tasks/paper_imports/paper_sources` 数据会拒绝升级，且禁止降级回匿名访问。保留旧数据须先备份并设计归属迁移；仅明确允许清理的开发库可使用受保护的重置流程。回退需恢复升级前备份。[迁移检查](../backend/alembic/versions/20261114_0004_user_accounts.py) · [开发库重置](../backend/README.md#104-已有开发库的受控重置)
