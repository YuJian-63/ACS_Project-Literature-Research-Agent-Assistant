# v3 数据库

v3 使用独立 PostgreSQL 实例/卷和全新初始迁移 `v3_0001`。不读取或迁移旧版本的数据。

| 表 | 用途 |
| --- | --- |
| users | 独立注册账号 |
| auth_sessions / auth_email_tokens / auth_mail_outbox / auth_rate_buckets | 登录会话、验证/重置、加密邮件发件箱和限流 |
| papers / paper_chunks | v3 的 PDF 元数据与解析原文 |
| paper_sources / paper_imports / source_request_gates | 来源追溯、导入任务、arXiv 访问调度 |
| agent_research / research_papers | 统一问题、状态、结构化结果和论文引用 |

研究没有 `task_type`。论文选择可为空，问题必填。研究与论文的关联带用户复合外键，防止跨用户引用；删除研究级联释放关联，仍被研究引用的论文禁止删除。

初始化后业务表为空，只预置一条 arXiv 调度 gate。`alembic_version` 记录 `v3_0001`。代码拒绝 `literature_v3` / `literature_v3_test_*` 以外的数据库名。文件存储与数据库同时独立，不把其他目录作为 PDF 回退来源。

PDF 文件大小上限为 50 MB（52,428,800 字节）；v3 通过 `v3_0003` 升级约束，保留独立迁移链与已有数据。
