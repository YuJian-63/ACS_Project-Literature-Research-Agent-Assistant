# v3 API 契约

所有 `/api/v1` 业务接口使用 v3 独立账号和会话；写入要求配置认可的来源与 CSRF token。账号、论文、搜索/导入端点保留原有行为。旧 `/api/v1/tasks` 不再存在。

## 统一研究

- `POST /api/v1/agent-research`：`{question, paper_ids?: UUID[], allow_search?: boolean}`。问题 1—8000 字符且不能全空白；论文 0—20 篇；默认允许搜索。当前执行尚未接入，合法请求返回 `503 AGENT_NOT_CONNECTED`。
- `GET /api/v1/agent-research?limit=20&offset=0&status=succeeded`：分页 `{items,total,limit,offset}`。条目包含 `id, question, status, paper_ids, papers, created_at`。
- `GET /api/v1/agent-research/{UUID}`：`{task_id, question, status, paper_ids, result, error}`。仅能读取自己的研究。
- `DELETE /api/v1/agent-research/{UUID}`：成功 204；不存在 404；运行中 409。仅删除本研究并释放引用，不删除 PDF。

`result` 后续接收 Agent 的 `TaskResult`：Markdown `answer` / `comparison_table`、`citations`、`sources`、`unresolved`、`stop_reason` 等。没有内容的字符串/数组应为空，不返回假结果。证据必须使用可追溯 chunk ID 与物理 PDF 页码，并把外部来源映射为有效本地论文 ID 后交给阅读器。

真实 Agent 的调度、库内优先检索、证据不足后的外部搜索、运行状态、幂等、超时及结果在线校验仍待实现。前端目前不要求后端返回执行轨迹或运行统计。
