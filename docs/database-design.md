# 后端数据库设计

后端使用 PostgreSQL 17、SQLAlchemy 和 Alembic。数据库保存账号、论文元数据、作业状态、研究结果与引用。原始 PDF 存在 `STORAGE_ROOT/uploads/<paper_id>.pdf`，备份和还原时应同时保留数据库与存储目录。本分支的迁移 head 为 `20261122_0013`。[业务模型](../backend/src/app/db/models.py) · [账号模型](../backend/src/app/db/accounts.py) · [迁移目录](../backend/alembic/versions)

## 账号与权限

| 表 | 用途 |
| --- | --- |
| `users` | 用户名、邮箱、规范化唯一键、密码哈希及账号状态。启用的账号须已验证邮箱。 |
| `auth_sessions` | 会话令牌的哈希、用户、到期和撤销时间。会话与用户的 `auth_version` 绑定。 |
| `auth_email_tokens` | 邮箱验证和密码重置令牌的哈希、用途、有效期及消费状态。 |
| `auth_mail_outbox` | 待投递邮件的加密载荷、重试次数、下次发送时间及 Worker 租约。 |
| `auth_rate_buckets` | 登录、注册和邮件申请等操作的限流计数及到期时间。 |

API 从认证信息确定用户。`papers`、`tasks`、`paper_sources` 和 `paper_imports` 都有 `user_id`。任务和论文之间、导入记录和论文之间使用包含 `user_id` 的复合外键，数据库会拒绝跨用户建立关联。查询研究结果与下载 PDF 时，API 仍按当前用户校验访问权限。

## 论文库与 arXiv 导入

| 表 | 用途 |
| --- | --- |
| `papers` | 每份 PDF 的用户、存储路径、原始文件名、标题、大小、SHA-256、物理页数及解析状态。单文件最大 50 MiB。 |
| `paper_sources` | 保存已导入论文的来源元数据。同一用户下，来源和带版本的 arXiv ID 联合唯一。 |
| `paper_imports` | 保存用户的导入作业、重试轮次、租约、已核验的来源元数据和成功后的本地论文 ID。 |
| `source_request_gates` | 多进程共享的 arXiv 请求节流状态，包括下次请求时间、当前持有者及上游要求的等待时间。 |
| `paper_chunks` | 保留早期任务使用的分页文本片段，供历史引用按原片段 ID 读取。 |

上传新文件后，Parser Worker 读取原始 PDF 并更新 `papers` 的标题、页数和状态。新研究的文本提取与分块由独立 Agent 完成。外部 arXiv 引用先保存在 Agent 原生结果中；用户确认导入对应版本后，论文库才建立本地记录。

## 研究任务、结果与引用

| 表 | 用途 |
| --- | --- |
| `tasks` | 用户提交的问题、运行器、冻结的执行配置与时限、任务状态、Worker 租约、使用量和错误。新任务使用独立 Agent，历史任务保留原运行器类型。 |
| `course_service` | 记录本轮课程 GPU 服务的启动者、作业号、地址和运行状态。 |
| `shared_model_endpoints` | 每个用户保存的课程模型服务地址。 |
| `agent_queue_settings` | 保存全站研究任务并发上限，默认 2，可选 1–4。 |
| `agent_runs` | 每个 Agent 任务一条执行记录，以 `task_id` 为主键。`dispatch_id` 唯一标识本次派发，`input_sha256` 校验输入清单；另存 `manifest`、平台作业号、停止原因和完整的原生结果 `result`。 |
| `task_papers` | 联合主键为 `(task_id, paper_id)`。关联当前用户库中的论文，并以 `(paper_id, paper_sha256)` 固定使用的 PDF 内容。 |
| `task_events` | 以 `(task_id, seq)` 记录有序状态、阶段和警告事件。序号与 `tasks.last_event_seq` 在同一事务更新。 |
| `artifacts` | 每个任务至多一条可展示产物。Agent 完成或部分完成时写入 Markdown。 |
| `citations` | 产物中的库内引用，记录引用编号、论文、物理页码和原文。新引用保留 Agent 的来源和片段标识，旧引用仍可通过 `chunk_id` 关联 `paper_chunks`。 |

`task_papers.selection_order` 区分预选论文和 Agent 在运行中找到的库内论文。

- **用户预选。** 统一研究接口按请求中的 `paper_ids` 顺序从 0 开始编号，最多 20 篇。非空序号在同一任务内唯一；开启搜索时可以不预选论文。
- **运行中发现。** 结果入库时，后端核验论文归属与 SHA-256，并核对引用页码，再新增 `selection_order = NULL` 的关联。研究记录的预选列表只取非空序号，发现的论文仍可通过结果引用打开。

任务删除会级联移除相关执行记录、事件、关联、产物和引用。只要库内论文仍被任务关联，外键就保护其原始 SHA-256 并阻止删除。

## 提交、租约与回传

1. **提交。** 后端检查用户、配额和预选论文，在同一事务写入任务、执行记录、预选关联及首条事件。幂等键对同一用户唯一；重复提交相同键和输入时返回已有任务，输入不同则返回冲突。
2. **执行。** Worker 用 `FOR UPDATE SKIP LOCKED` 领取排队任务，以 `worker_id` 和 `lease_expires_at` 表示所有权，定期续租。远程提交与模型调用发生在数据库事务之外。租约过期且仍在任务时限内，Agent 任务可重新入队，以原 `dispatch_id` 和作业回执继续跟踪；截止时间从首次领取起算。
3. **回传。** 后端核对派发标识、输入清单摘要、任务身份和引用来源。只有仍持有效租约的 Worker 可以写回。在一个事务内保存原生结果、可展示产物及引用，并更新终态。`completed` 和 `partial` 均有可读结果，`partial` 另存未解决项；其他研究停止原因可保存原生结果并将任务标记为失败。[任务生命周期](../backend/src/app/tasks/lifecycle.py) · [结果入库](../backend/src/app/agent_bridge/store.py)

## 数据库迁移

在 `backend/` 运行 `uv run --locked alembic upgrade head`。升级后核对 `alembic current` 与 `alembic heads` 一致，并运行 `alembic check` 检查结构漂移。`backend/sql/schema.sql` 提供 DDL 对照。[后端迁移说明](../backend/README.md#4-迁移维护)

`0007` 引入 `agent_runs` 和原生引用标识，并兼容历史 Agent 分支的旧库。`0008` 将 PDF 上限提高到 50 MiB。`0009` 允许 `selection_order` 为空，原有预选编号保持有效。已有动态论文关联时，退回 `0008` 的非空约束会失败。

<a id="114-0004-升级重置与回退边界"></a>

### 从旧匿名库升级

早于 `20261114_0004` 的数据库缺少账号归属。若 `papers`、`tasks`、`paper_imports` 或 `paper_sources` 任一表已有记录，`0004` 会拒绝升级。需要保留旧数据时，先备份数据库与 PDF，并设计、核验归属迁移。仅在明确允许清理的开发库上使用受保护的重置流程。`0004` 禁止降级回匿名访问，回退需恢复已核验的升级前备份。[迁移检查](../backend/alembic/versions/20261114_0004_user_accounts.py) · [开发库重置说明](../backend/README.md#104-已有开发库的受控重置)
