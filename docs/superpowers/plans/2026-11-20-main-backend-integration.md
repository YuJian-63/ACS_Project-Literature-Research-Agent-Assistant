# main 与 backend-dev-v2 对接整理

目标：将远程 main 合并到 backend-dev-v2，以 main 的前端和 Agent 新行为为准，保留后端上传 PDF、派发和结果持久化能力。

## 实施范围

1. 获取 origin/main，保留原 GitHub Desktop stash，不删除或直接整体应用。
2. 三处 Agent 冲突先使用 main 完整版本，再添加后端本地来源所需的兼容，不还原旧历史压缩/收尾实现。
3. main 的 `20261118_0006` 保持论文导入元数据迁移；Agent 迁移后移到 `20261120_0007`。兼容之前同编号但已包含 Agent 表的数据库，保留任务数据，补上缺失元数据字段。
4. 恢复 stash 中已实现的后端只读论文库 API 及测试，不用旧 Agent 修改覆盖 main 的最终作答和语义检索实现。
5. 核对前端使用的论文、研究任务、删除、结果、证据字段及认证接口；需要兼容的展示数据由后端整理。
6. 运行 Agent 离线测试、后端测试、真实 PostgreSQL 迁移/权限/派发测试和前端构建，最后建立本地合并提交，不推送。

## 核心验收

- main 的前端文件保持原样；Agent 保留上下文压力收尾和 extension 检索实现。
- 原始 PDF 通过验证后的 manifest 读取；local 来源、物理页码、引用和 SHA-256 不变。
- 空库、main 元数据旧库、历史 Agent 旧库均可升级到唯一 head，已有 Agent 记录不丢失。
- 前端现有响应格式继续展示正文、Markdown 比较表和引用；Agent 原生比较表仍通过兼容正文展示，专用结构化比较视图见前端适配待办。任务删除/论文删除仍遵守所有权与外键约束。
- 自动测试不调用真实模型、arXiv 或 TACC；远程联调另行进行。

## 实施与验证结果（2026-11-20）

- 已获取并合并 origin/main `bd67fbe`；前端文件与该 main 完全一致。冲突文档保持 main，baseline 仅补回受控 local 来源、引用识别和 UTF-8 输入输出兼容。
- main 新增 extension / retrieval / embeddings 保持原样，新的上下文压力最终作答与本地 PDF 的组合已有离线测试覆盖。未将旧 Agent 暂存实现覆盖 main。
- 已恢复暂存中的后端论文库 token、标题/文件名多关键词 AND/OR 检索和 PDF 下载 API；原 GitHub Desktop stash 对象保持不变。
- 唯一迁移 head 为 `20261120_0007`；原 SQL 参考结构同步到 ORM。空库、main 旧库、历史 Agent 旧库升级及保留 Agent 记录均通过真实 PostgreSQL 17 测试。
- 已补充 Agent 恢复中 queued 状态的删除保护，防止远端仍在运行时删除派发记录；未开始任务和完成任务继续允许删除，原论文保留。
- 后端：251 项测试全部通过，无跳过，包含认证/所有权、论文库 API、独立进程 PDF 往返、派发与恢复、迁移及 main 的删除/导入逻辑。测试使用独立临时数据库，容器结束后清理。
- Agent：260 passed、4 skipped；跳过项为未启用的真实 Neon 测试与 Windows 缺少符号链接创建权限的三个夹具。修改的 Agent 文件 Ruff 检查通过。
- 前端：`npm run build` 通过，包含 TypeScript 检查；未启动浏览器进行人工验收。
- 本轮不调用真实模型、arXiv 或 TACC，不执行 ECS 部署，不推送远程。后端现有派发仍开放 baseline；extension 工作流和原生 Agent 专用前端视图留待后续显式接入。
