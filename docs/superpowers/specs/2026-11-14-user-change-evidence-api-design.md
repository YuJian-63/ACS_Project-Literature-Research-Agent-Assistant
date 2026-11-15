# 用户改动：论文原文片段 HTTP API 设计

日期：2026-11-14
归属标记：user-change（用户发起的改动，由 Codex 协助实现）
状态：待用户确认；尚未实施

## 目的与范围

为外部 Agent 提供已解析论文的只读原文分页接口。复用现有内部
`app.papers.evidence.read_evidence`，不修改解析、研究流程或数据库结构。
历史设计、计划和开发记录保持原样；本次后续计划与验证记录另建带
`user-change` 标记的文件。不改动用户已有 README.md 修改。

## 方案

采用现有 FastAPI papers 路由包装内部读取函数，新增显式响应模型，
让 OpenAPI 可供 Agent 开发者使用。另起服务会重复数据库和生命周期逻辑；
一次性返回全文会失去现有读取上限，因此本次采用分页路由。

## 接口契约

`GET /api/v1/papers/{paper_id}/evidence?after_index=-1&limit=100`

- paper_id：UUID。
- after_index：整数，最小 -1，默认 -1；仅返回 chunk_index 严格大于游标的片段。
- limit：整数，1—100，默认 100。
- 按 chunk_index 升序返回，沿用内部函数现有字段和分页语义。
- 顶层字段：paper_id、paper_sha256、page_count、parser_version、items、has_more、next_after_index。
- items 字段：chunk_id、paper_id、chunk_index、page_number、content、content_sha256、parser_version。
- page_number 为从 1 开始的 PDF 物理页码。
- 论文不存在：404 PAPER_NOT_FOUND；非 ready：409 PAPER_NOT_READY。
- 非法 UUID 或查询参数：422，沿用项目统一 INVALID_REQUEST 错误格式。
- 最后一页或越界游标：200，has_more=false；空页游标保持输入值。

## 运行边界

沿用当前受信本机单用户、无鉴权的部署边界，不增加公网部署或访问控制。
接口不暴露文件路径或模型密钥，不调用模型，不写入业务数据。

## 验证与交付

新增 HTTP 测试覆盖分页衔接、最后一页和空页、错误响应、参数上下界及
OpenAPI 响应结构；优先复用项目 unittest 风格。测试环境及未验证边界
如实写入新的 user-change 开发记录，并提供 Agent 调用示例。

## 确认记录追加（2026-11-14）

用户在本会话回复“确认”，批准以上设计；后续实施及验证记录另见
`docs/2026-11-14-user-change-evidence-api.md`。上文初始状态保留为设计历史。
