# Literature Research Agent Assistant — API 契约

版本：v1 · 更新日期：2026-11-13。已实现 API/Mock Worker、独立 PDF Parser、真实摘要/问答 Runner、多论文综述及第 10 节 arXiv 搜索/导入接口。用户已完成 MVP-3 的隔离原生 PostgreSQL 八组专项验收、真实 arXiv 单版本搜索/下载/解析及浏览器 Mock 任务闭环；另已完成一次 DeepSeek 真实单篇摘要及人工引用/刷新核验，真实问答与多论文综述仍待验收。详细证据范围见实施记录；启动方式见 `backend/README.md`。

需求依据：`docs/Proposal.md` 第 2、3 节。数据库设计见 `docs/database-design.md`，参考 DDL 见 `backend/sql/schema.sql`。

## 1. 基本约定与范围

- 业务前缀 `/api/v1`；开发默认 origin 为 `http://localhost:8000`；`/health`、`/ready` 不带前缀。
- MVP 为受信本地环境的单用户应用，不建用户/租户表；公开部署前须另行实现身份与资源访问控制。
- 前端只访问应用后端，不直接访问数据库、LangGraph 或模型服务。
- JSON 使用 UTF-8、snake_case 字段；ID 使用 UUID；时间使用 RFC 3339 UTC 字符串，以 `Z` 结尾。
- 单个对象直接返回，列表返回分页对象；未知请求体字段返回 422。
- 所有响应返回 UUID 格式的 `X-Request-ID`，用于定位日志，不用于鉴权。
- 普通列表默认 `limit=20, offset=0`；limit 为 1—100，offset 非负；按 `created_at DESC, id DESC` 排序，不保证跨请求快照一致。
- 创建论文返回 201，创建异步任务返回 202；错误统一采用第 8 节的结构。
- 当前不提供删除、取消、研究任务原地重试、SSE 或模型配置写入接口；arXiv 搜索和导入显式重试见第 10 节，默认关闭联网。

| 阶段 | 范围 |
| --- | --- |
| MVP-0 | 上传 PDF、持久化任务、Mock Runner、轮询、明确标注的模拟结果 |
| MVP-1A | 本地文本 PDF 解析、按物理页码保存片段、摘要/问答/综述任务前置要求解析就绪 |
| MVP-1B | 真实 Runner、证据引用校验与摘要/问答 |
| MVP-2 | 已实现跨论文综述与比较；不包含搜索或扩展工作流 |
| MVP-3 | 已实现 arXiv 单源搜索、指定版本 PDF 导入与解析；外部服务验收待配置 |

`extended` 是保留枚举，当前返回 `422 WORKFLOW_NOT_AVAILABLE`。`is_mock` 由服务端 TASK_RUNNER 配置决定，不能由请求指定；默认 mock，langgraph 提供真实摘要、问答和多论文综述；搜索/导入不调用模型。

## 2. 资源与状态

### 2.1 Paper

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 论文 ID |
| title | string | 1—255 字符，首版由文件名去掉扩展名生成 |
| original_filename | string | 1—255 字符，不含路径或控制字符 |
| content_type | string | 统一为 application/pdf |
| size_bytes | integer | 实际文件大小，1—20,971,520 |
| sha256 | string | 64 位小写十六进制摘要 |
| status | string | uploaded / processing / ready / failed |
| page_count | integer / null | 物理 PDF 页数，已知时为正数 |
| parser_version | string / null | 真实解析器版本，Mock 阶段为 null |
| error | Error / null | 仅 failed 时非空 |
| created_at, updated_at | datetime | 创建/修改时间 |

生命周期为 `uploaded → processing → ready / failed`。独立 Parser Worker 未启动时论文保持 uploaded。MVP-1A 仅支持可提取文本的 PDF，不运行 OCR；损坏、加密、纯扫描件和解析超限会进入 failed，需重新上传来重试。ready 表示文本已提取，不表示论文已被 Agent 分析。PDF 页码从 1 开始，表示物理页序号，空白页不会造成后续页号偏移，不使用印刷页码。服务器不返回 storage_key、解析租约或绝对路径。

### 2.2 Task

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 任务 ID |
| task_type | string | summary / qa / review |
| question | string / null | 规范化后的问题 |
| paper_ids | UUID[] | 选定论文，按 UUID 升序返回 |
| workflow_type | string | baseline / extended |
| is_mock | boolean | Runner 为 mock 时为 true |
| status | string | queued / running / succeeded / failed |
| stage | string | 阶段代码，不作为判断终态的依据 |
| budget | Budget | 执行预算快照 |
| versions | object | model_id、workflow_version、prompt_version、dataset_version；未知值为 null |
| stats | TaskStats | 实际统计，未知值为 null |
| last_event_seq | integer | 最新持久化事件序号，最小为 0 |
| error | Error / null | 仅 failed 时非空 |
| created_at, updated_at | datetime | 创建/修改时间 |
| started_at, finished_at | datetime / null | 开始/结束时间 |

```text
queued → running → succeeded
   │         └──→ failed
   └────────────→ failed
```

终态不可回退，重试创建新任务。queued → failed 仅用于调度前失败。Worker 领取后使用数据库租约，失联、超时、预算耗尽和 Agent 异常都必须变为明确的 failed。

阶段示例：queued、mock_preparing、mock_generating、mock_completed、parsing、searching、retrieving、writing、checking、completed、failed。客户端容忍新增阶段；只有 status 决定是否停止轮询。

**Budget：**

| 字段 | 默认值 | 硬上限范围 |
| --- | --- | --- |
| max_steps | 10 | 1—100 |
| max_tokens | 8000 | 1—100000 |
| timeout_seconds | 120 | 1—1800 |

budget 可省略或只提供部分字段；缺项填默认值，部署配置可收紧上限。max_tokens 是任务累计输入与输出 token 预算，模型单次上下文限制另外检查；超时从开始执行计算，不含排队。真实 Runner 在步骤/调用边界检查预算，超出即失败；Mock 不伪造模型用量。

**TaskStats：**

- queue_ms = started_at − created_at，未开始为 null。
- execution_ms = finished_at − started_at，未开始或未结束为 null。
- end_to_end_ms = finished_at − created_at，未结束为 null。
- input_tokens、output_tokens、model_calls、tool_calls 为非负整数或 null。
- total_tokens 仅在输入、输出均已知时返回二者之和，否则为 null。

时间差按毫秒取整。Mock 的模型/工具统计及 model_id 均为 null；其实际排队/执行耗时仍可计算。不得把上述耗时当成模型侧 TTFT、TPOT 或 GPU 指标。

## 3. 健康检查

### GET /health

进程存活，不访问数据库或模型；200：

```json
{"status": "ok"}
```

### GET /ready

检查数据库连接和预期迁移版本，不调用模型；200：

```json
{"status": "ready"}
```

未就绪返回 `503 SERVICE_NOT_READY`，使用统一错误结构，不暴露数据库地址和凭据。

## 4. 论文接口

### POST /api/v1/papers

Content-Type 为 multipart/form-data，仅包含一个必填的 file 字段。

- 文件最大 20 MiB（20,971,520 字节）；服务端分块接收并累计大小，不仅依赖 Content-Length 或前端校验。
- 原始文件名以 `.pdf` 结尾，大小写不敏感；拒绝路径分隔符、空字节及控制字符。
- 校验 `%PDF-` 文件头，文件 MIME 仅作参考；这不等同于完整解析，损坏/无文本的 PDF 仍可能在后续解析失败。
- 服务端生成 UUID，写入 `STORAGE_ROOT/uploads/{paper_id}.pdf`；客户端不能指定路径。
- 重复上传同一内容仍返回 201 和新 paper_id；sha256 用于来源核验，首版不做内容去重。
- 文件写入与数据库事务需异常补偿，详见数据库设计。

201 返回完整 Paper：

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "title": "sample-paper",
  "original_filename": "sample-paper.pdf",
  "content_type": "application/pdf",
  "size_bytes": 1024,
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "status": "uploaded",
  "page_count": null,
  "parser_version": null,
  "error": null,
  "created_at": "2026-11-10T01:00:00Z",
  "updated_at": "2026-11-10T01:00:00Z"
}
```

错误：413 FILE_TOO_LARGE；415 UNSUPPORTED_MEDIA_TYPE（请求不是 multipart）；422 INVALID_PDF / INVALID_FILENAME / INVALID_REQUEST；500 STORAGE_WRITE_FAILED。空文件属于 INVALID_PDF。

### GET /api/v1/papers

参数：limit、offset；可选 status（Paper 状态）、q（1—200 字符，按标题/原文件名做字面子串搜索，不是网络检索）。200 返回分页对象，items 每项为完整 Paper：

```json
{"items": [], "total": 0, "limit": 20, "offset": 0}
```

### GET /api/v1/papers/{paper_id}

200 返回完整 Paper，用于查询解析状态；不存在返回 `404 PAPER_NOT_FOUND`；UUID 格式错误返回 422。

### GET /api/v1/papers/{paper_id}/file

200 返回 PDF 字节；Content-Type 为 application/pdf，Content-Disposition 使用 inline 及安全编码的原文件名，设置 X-Content-Type-Options: nosniff。首版不承诺 HTTP Range 支持。

数据库记录不存在返回 `404 PAPER_NOT_FOUND`；已有记录但文件不可读返回 `500 FILE_UNAVAILABLE`。路径来自受控存储键，必须验证其位于 STORAGE_ROOT 内，不接受用户路径。

## 5. 任务接口

### POST /api/v1/tasks

Content-Type 为 application/json；可选 Idempotency-Key 请求头，语义见第 5.1 节。

```json
{
  "task_type": "qa",
  "question": "这篇论文的核心方法和局限是什么？",
  "paper_ids": ["11111111-1111-4111-8111-111111111111"],
  "workflow_type": "baseline",
  "budget": {"max_steps": 10, "max_tokens": 8000, "timeout_seconds": 120}
}
```

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| task_type | 是 | summary、qa 或 review |
| question | 条件必填 | 去首尾空白；qa/review 为 1—8000 字符；summary 可省略或为 null，空白归一为 null，非空时同样为 1—8000 字符；超长返回 422 INVALID_REQUEST |
| paper_ids | 是 | summary/qa 恰好 1 篇；review 为 2—20 篇；UUID 不得重复 |
| workflow_type | 否 | 默认 baseline，MVP-0 不开放 extended |
| budget | 否 | 见 Budget，缺失字段填默认值 |

paper_ids 视为集合，转 UUID 标准字符串后排序。不存在论文返回 404，details.missing_paper_ids 列出缺失 ID。Mock 允许 uploaded/ready，processing/failed 返回 409 PAPER_NOT_READY；真实 Runner 只允许 ready。真实模式需配置 `LLM_BASE_URL`、`LLM_MODEL_ID` 和 `LLM_API_KEY`；缺少任一项时返回 `503 RUNNER_NOT_CONFIGURED`，不创建任务且不降级为 Mock。真实模式支持 summary、qa 及 review；review 要求全部 2—20 篇论文 ready。

runner_type、is_mock、model_id、status、stage、thread_id 及存储配置均不接受客户端写入。后端冻结 Runner、工作流版本和模型等执行配置，后续配置变更不能改变已提交任务。

新建真实 review 由服务端冻结内部 `run_config.max_output_tokens=4096`，该字段不是客户端请求参数，不增加公开任务/产物字段。模型单次输出上限为冻结值与剩余预估总 Token 预算的较小值；预估输入已耗尽总预算时不调用模型。旧任务缺少字段时保持 2048，含既有 review-v2；summary/qa 保持 2048，Mock 不变。持久化值仅允许精确整数（review 为 2048/4096，单篇为 2048），非法配置在调用前失败。实际用量仍受原总预算约束，时间预算、单次调用、严格引用与原子写入不变；4096 不保证完整输出，不自动重试/续写或修复 JSON。重建任务是新提交；旧任务和原幂等键的重放不升级输出上限。

新建真实 summary/qa 任务的 versions.prompt_version 为 `evidence-v4`。后端从已选存储片段生成最长 1000 字符的连续证据摘录，保留内部排版与 Unicode，不跨片段或物理页码，并分配任务内 evidence_id。内部模型结果按 paragraphs 返回每段正文与 evidence_ids，后端解析 ID、取原样引文与来源身份、按首次使用顺序分配引用编号，再执行原有严格来源、逐字引文及大小校验。跨段同一证据共享编号；未知 ID、同段重复 ID、模型自写引用标记或额外引文/来源字段会失败，不进行模糊匹配或静默替换。paragraphs/evidence_ids 不是对外 API 字段，产物仍返回 content_markdown 与 citations。

新建真实 review 的 versions.prompt_version 为 `evidence-review-v2`，workflow_version 仍为 `langgraph-review-v1`。输入沿用原样证据摘录并标明所属 paper_id，evidence_id 在任务内唯一。内部模型返回 paragraphs 和 comparison_table；段落包含 content_markdown/evidence_ids，表格单元格包含 value/evidence_ids，不接收模型自报引文、页码或引用编号。后端先按段落、再按选定论文和声明列顺序解析 ID，跨正文与表格共享首次使用编号，允许仅在表格使用的引用。非 null 研究单元格必须引用本行论文；null 必须使用空 evidence_ids。未知 ID、同段/同单元格重复证据、跨论文单元格引用、模型自写引用标记或额外字段均会失败。后端生成原协议草稿后仍执行既有严格综述校验，外部 content_markdown/citations/comparison_table 结构不变。

Runner 按已保存版本构造提示词、估算输入预算并选择解析器；历史 `evidence-v1`/`evidence-v2`/`evidence-v3` 和 `evidence-review-v1` 任务仍使用原提示词和严格校验，未使用引用或非逐字引文仍导致失败；缺少提示版本的旧 review 回退至 v1。版本由服务端决定，不接受客户端指定；幂等重放返回原任务，不切换版本。不增加模型调用、自动重试或失败时发布产物的行为。

服务端可选 `LLM_THINKING_MODE=provider_default|disabled|enabled`，随真实任务冻结为 run_config.model_thinking_mode；不接受客户端指定。provider_default 不向模型发送 thinking 字段，另外两项发送对应 thinking.type，仅适用于支持该扩展的服务。旧任务缺少字段时使用 provider_default；不改变现有 Token/时间预算或引用校验。

真实结果校验失败仍为 `INVALID_AGENT_RESULT`；新失败的 error.details 可包含 validation_reason（固定安全分类，如 invalid_json/schema_mismatch/quote_mismatch/unknown_evidence/unused_citation）与 model_finish_reason（白名单结束原因、unknown 或 null）。错误消息说明对应类别；不返回原始响应、引文、密钥或底层校验异常文本。历史失败 details={} 保持有效，不能追溯补齐。诊断不改变校验规则、自动重试策略或失败不发布产物的约定。

202 返回 TaskAccepted；首次为 queued，幂等重放返回已有任务的当前状态：

```json
{
  "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "task_type": "qa",
  "workflow_type": "baseline",
  "is_mock": true,
  "status": "queued",
  "stage": "queued",
  "created_at": "2026-11-10T01:00:01Z"
}
```

Location 响应头为 `/api/v1/tasks/{task_id}`。202 表示任务、论文关联和首个事件已提交，不表示执行已开始或完成。

### 5.1 幂等提交

- 可省略 Idempotency-Key；提供时为 1—128 个 ASCII 可见字符，不含空白。一次提交使用新键，网络重试复用。
- 单用户 MVP 使用全局唯一键；未来多用户按用户/工作区限定。首版不自动过期或复用键。
- request_hash 对规范化后的 task_type、question、排序的 paper_ids、workflow_type、补齐默认值的 budget 计算 SHA-256；JSON 使用 UTF-8、递归按键排序、无多余空格、不转义非 ASCII 字符。
- 同键同哈希返回原任务，仍为 202，Idempotency-Replayed 响应头为 true；新任务为 false。
- 同键不同哈希返回 `409 IDEMPOTENCY_CONFLICT`；并发由数据库唯一约束及冲突后重查保证只创建一项。
- 请求规范化后先查幂等键；同请求重放不重新检查论文当前状态，首次提交仍完整校验。
- 无键时相同请求可创建多个任务；主动重跑失败任务必须使用新键。

### GET /api/v1/tasks

参数：limit、offset；可选 status、task_type、workflow_type、is_mock（true/false）。返回普通分页对象，items 为 TaskSummary：id、task_type、question、paper_ids、workflow_type、is_mock、status、stage、error、created_at、updated_at、started_at、finished_at。无匹配结果返回空 items，不返回 404。

### GET /api/v1/tasks/{task_id}

200 返回完整 Task。以下为 Mock 成功示例；数值仅演示契约，不是实验测量：

```json
{
  "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "task_type": "qa",
  "question": "这篇论文的核心方法和局限是什么？",
  "paper_ids": ["11111111-1111-4111-8111-111111111111"],
  "workflow_type": "baseline",
  "is_mock": true,
  "status": "succeeded",
  "stage": "mock_completed",
  "budget": {"max_steps": 10, "max_tokens": 8000, "timeout_seconds": 120},
  "versions": {"model_id": null, "workflow_version": "mock-v1", "prompt_version": null, "dataset_version": null},
  "stats": {
    "queue_ms": 1000, "execution_ms": 3000, "end_to_end_ms": 4000,
    "input_tokens": null, "output_tokens": null, "total_tokens": null,
    "model_calls": null, "tool_calls": null
  },
  "last_event_seq": 5,
  "error": null,
  "created_at": "2026-11-10T01:00:01Z",
  "updated_at": "2026-11-10T01:00:05Z",
  "started_at": "2026-11-10T01:00:02Z",
  "finished_at": "2026-11-10T01:00:05Z"
}
```

不存在返回 `404 TASK_NOT_FOUND`。查询 failed 任务仍返回 200，执行错误位于 Task.error，不能将任务失败等同于查询接口失败。

### GET /api/v1/tasks/{task_id}/events

after_seq 默认 0，非负；limit 默认 100，范围 1—500。按 seq 升序返回严格大于游标的事件。

```json
{
  "items": [{
    "task_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "seq": 1, "event_type": "status", "status": "queued", "stage": "queued",
    "message": "任务已加入队列", "payload": {}, "created_at": "2026-11-10T01:00:01Z"
  }],
  "next_after_seq": 1, "has_more": false
}
```

event_type 为 status/stage/warning/error。payload 为脱敏的 JSON 对象，不返回密钥、完整提示词、堆栈或服务器路径。无新事件时 items=[]、next_after_seq 保持原游标、has_more=false；任务不存在返回 404。

## 6. 产物、比较表与引用

### GET /api/v1/tasks/{task_id}/artifacts

200 返回 `{"items": [...]}`；当前每个任务最多一个研究结果，仍使用数组便于扩展。

- queued/running/failed 返回空数组，不展示部分生成结果。
- succeeded 必须已有且仅有一项产物；产物、引用和成功状态在一个事务中提交。
- 任务不存在返回 404。

Mock 示例：

```json
{
  "items": [{
    "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "task_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "task_type": "qa", "schema_version": 1, "is_mock": true,
    "title": "论文问答（模拟结果）",
    "content_markdown": "## 模拟结果\n用于验证任务流程，尚未解析或分析论文，不代表论文结论。",
    "comparison_table": null, "citations": [],
    "created_at": "2026-11-10T01:00:05Z"
  }]
}
```

Artifact 字段如上；is_mock、task_type 从任务派生，数据库不重复保存。content_markdown 非空且 UTF-8 编码最大 2 MiB；前端禁用原始 HTML 渲染。统计读取 Task.stats，不在产物中维护第二份。

### 6.1 ComparisonTable

summary/qa 的 comparison_table 为 null；真实 review 使用下述对象。Mock review 允许 null，但必须显示模拟提示。

```json
{
  "columns": [
    {"key": "method", "label": "方法"},
    {"key": "limitations", "label": "局限"}
  ],
  "rows": [{
    "paper_id": "11111111-1111-4111-8111-111111111111",
    "cells": {
      "method": {"value": "方法描述示例", "citation_keys": ["C1"]},
      "limitations": {"value": null, "citation_keys": []}
    }
  }]
}
```

此片段仅解释结构，不是完整真实 review；真实 review 至少两篇论文。

- columns 为 1—12 项；key 唯一且匹配 `[a-z][a-z0-9_]{0,31}`；label 为 1—80 字符。
- rows 恰好覆盖任务选定论文，每篇一行；cells 的键与 columns 完全一致。
- value 为 1—4000 字符的非空字符串或 null；null 显示“未报告”，不能猜测。实验条件不同显式写“不可比较：原因”。
- citation_keys 不重复，必须引用同一 artifact 中存在且属于该行 paper_id 的引用。
- 非 null 的研究内容至少有一条同论文引用；null 的引用列表必须为空。新 review 的模型内部 evidence_ids 由服务端解析和统一编号，历史 v1 的内部引用序号须经服务端校验后转换为 C 编号；均不能直接信任模型自报的 citation_keys。
- 数据库仅校验 JSON 外层结构，完整规则由结果写入服务校验，不能直接信任模型输出的 JSON。

真实 review 的总上下文最多 32 个存储片段，并受冻结的 evidence_context_chars 限制；v2 可将单个存储片段划分为多条不跨页的原样摘录，32 限制针对存储片段而非摘录条数。为每篇有片段论文至少预留一个最短片段，不足时任务以 BUDGET_EXCEEDED 失败且不调用模型。所有选定论文均无片段时，服务端返回证据不足正文与 evidence_status（证据状态）单列比较表，每行值为“未检索到可用解析证据”，无引用；该系统状态不是研究结论，允许非 null 且无引用。此路径 input_tokens、output_tokens、total_tokens、model_calls、tool_calls 均为 0。新 review 使用 langgraph-review-v1/evidence-review-v2，旧任务保留 v1；表格按任务冻结的选定顺序排列，部分无证据论文的研究内容 cell 必须为 null。

### 6.2 Citation

真实引用结构示例，内容仅演示格式：

```json
{
  "id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  "citation_key": "C1",
  "paper_id": "11111111-1111-4111-8111-111111111111",
  "paper_title": "Example research paper",
  "chunk_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  "page_number": 3,
  "quote": "A verbatim passage from the stored paper chunk."
}
```

- citation_key 在产物内唯一，格式为 C 加正整数；正文用 `[C1]` 标记，不是 UUID。
- chunk 必须属于该 paper；page_number 必须等于 chunk 的物理页码；paper 必须属于任务选定集合。
- quote 为非空原文，必须是已存储 chunk.content 的原样子串。文本清理先于固定存储，之后从存储文本取引用。
- 每个 chunk 不跨页；多页证据使用多个引用。前端提供论文文件入口、页码和原文侧栏。
- Mock 引用必须为空。真实产物来源校验失败以 INVALID_AGENT_RESULT 结束任务，不编造证据补齐。
- 无证据时允许输出明确的“证据不足”说明和空引用，不能给出无支持的肯定结论；来源一致不等于语义支持率合格。

## 7. 前端轮询与失败处理

1. 提交成功后按任务 ID 跳转详情页。
2. 立即 GET Task，再每 2 秒轮询；上一次请求未结束时不叠加请求。
3. 可按 events 游标拉取增量记录；刷新从服务端恢复，不依赖浏览器内存。
4. 网络或 503 错误显示“查询失败”，保留最后状态，提供重试查询；不能改成任务 failed。
5. succeeded/failed 停止轮询，卸载组件取消请求并清理计时器。
6. succeeded 查询 artifacts；failed 展示 Task.error；重跑创建新任务。
7. is_mock 为 true 时持续显示“模拟运行/模拟结果”，排除出模型效果评估。

## 8. 统一错误结构

HTTP 错误使用以下 envelope：

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "qa 任务的问题不能为空",
    "details": {
      "fields": [{"location": "body.question", "message": "去除首尾空白后至少包含一个字符"}]
    }
  }
}
```

Task.error/Paper.error 直接使用内层 `{code,message,details}`，正常为 null。details 必须为对象，无附加信息时为 `{}`；不能包含密钥、堆栈或服务器路径。

| HTTP 状态/场景 | code | 说明 |
| --- | --- | --- |
| 404 | PAPER_NOT_FOUND / TASK_NOT_FOUND | 资源不存在 |
| 409 | PAPER_NOT_READY | 论文状态不允许执行 |
| 409 | IDEMPOTENCY_CONFLICT | 幂等键已绑定不同请求 |
| 413 | FILE_TOO_LARGE | 文件超过 20 MiB |
| 415 | UNSUPPORTED_MEDIA_TYPE | 上传请求不是 multipart |
| 422 | INVALID_REQUEST | 缺字段、非法 UUID/枚举、数量、重复 ID、预算、未知字段等 |
| 422 | INVALID_PDF / INVALID_FILENAME | 文件内容或名称不合法 |
| 422 | WORKFLOW_NOT_AVAILABLE | 扩展工作流未开放 |
| 422 | TASK_TYPE_NOT_AVAILABLE | 真实 Runner 当前不支持该任务类型 |
| 500 | STORAGE_WRITE_FAILED / FILE_UNAVAILABLE | 文件写入/读取失败 |
| 500 | INTERNAL_ERROR | 未预期接口错误 |
| 503 | SERVICE_NOT_READY | 数据库/迁移未就绪 |
| 503 | RUNNER_NOT_CONFIGURED | 真实 Runner 缺少模型服务配置，任务不会创建 |
| Task.error | WORKER_LOST | Worker 租约过期 |
| Task.error | TASK_TIMEOUT / BUDGET_EXCEEDED | 超时/预算耗尽 |
| Task.error | AGENT_EXECUTION_FAILED / INVALID_AGENT_RESULT | Agent 异常/产物不合法 |
| Task.error | PAPER_SOURCE_CHANGED / PAPER_NOT_READY | 任务执行期间选定论文来源变化或不再就绪 |
| Paper.error | PDF_INVALID / PDF_ENCRYPTED / PDF_NO_TEXT / PDF_LIMIT_EXCEEDED / PDF_PARSE_TIMEOUT / PARSER_LOST / PDF_SOURCE_CHANGED / FILE_UNAVAILABLE | 文本解析失败，需查看 message 并重新上传 |

FastAPI 默认校验异常也必须转换为相同格式，不能遗留第二种 422 响应。

## 9. 数据映射与验收

| API 资源/字段 | 数据来源 |
| --- | --- |
| Paper | papers，不暴露存储键/租约 |
| Task、Budget、versions | tasks + task_papers |
| TaskStats | tasks 统计列/时间差，total_tokens 派生 |
| Event、last_event_seq | task_events + tasks.last_event_seq，事务内同步 |
| Artifact | artifacts + tasks 派生 task_type/is_mock |
| Citation | citations + paper_chunks，不在产物 JSON 中重复保存 |
| ComparisonTable | artifacts.comparison_table JSONB，服务层完整校验 |

首批验收覆盖上传异常、论文数量/状态、幂等并发、无 Worker 时保持 queued、租约失败、产物与成功原子提交、刷新恢复、事件游标、Mock 标识及空引用、跨论文/错页引用拒绝、统一错误格式。

FastAPI 实现阶段从 Pydantic 生成 OpenAPI，并逐项核对本文，不同时手工维护另一份易漂移的 OpenAPI。

## 10. MVP-3：arXiv 搜索与导入

本节接口已实现。2026-11-13 用户完成隔离原生 PostgreSQL 专项验收及真实 arXiv 单版本搜索/导入/解析与 Mock 任务闭环；证据范围见 `docs/superpowers/plans/2026-11-12-mvp-3-arxiv-search-import.md`。限流、安全、补偿与 UI 细节见 `docs/superpowers/specs/2026-11-12-mvp-3-arxiv-search-import.md`。

### 10.1 类型与版本身份

- provider 固定 arxiv；external_id 最长 80 字符，必须带明确正整数 vN，支持新旧标识；拒绝 URL、无版本 ID、路径/查询注入。
- 时间、UUID、未知字段处理沿用基本约定。搜索结果不等于 Paper，未下载前不进入可研究论文库。
- PaperResponse 增加 `source: PaperSource | null`，手动上传为 null。PaperSource 为 provider/external_id/title/authors/abstract/doi/categories/published_at/source_updated_at/abstract_url/pdf_url；链接由服务端从 ID 生成。
- 元数据上限：title 2000 字符、abstract 20000、authors 200 项/每项 300、categories 50 项/每项 64、doi 可空/512。拒绝 NUL/无效 UTF-8；数组可空，title/作者项/分类项须非空，abstract 可空字符串。

### GET /api/v1/paper-search

q 必填，规范化后 1—200 字符/最多 20 词，普通关键词而非原始高级语法。limit 默认 10/范围 1—20；offset 默认 0/范围 0—1000。不接受上游 URL/provider/排序。

200：`{items: SearchPaper[], total: number, limit: number, offset: number}`。SearchPaper 为 PaperSource 加可空 import_id/import_status/paper_id/paper_status。import_status 为 queued/running/succeeded/failed；paper_status 为既有 PaperStatus。total 是上游本次报告，不保证跨页快照。

成功上游数据缓存 600 秒/每进程最多 100 页，本地导入/解析投影每次重查。无匹配返回空数组和 total=0；offset 越过结果末尾时 items=[]，但保留上游 total。上游错误不能伪装空结果。

### POST /api/v1/paper-imports

请求：`{"provider":"arxiv","external_id":"1706.03762v7"}`。不接受客户端元数据、URL 或 storage_key。

按版本自然键创建/复用，不在提交时下载。queued/running 返回 202，已 succeeded/failed 返回 200，均为 PaperImport。无需 Idempotency-Key；普通重复 POST 不能重试 failed 或生成重复 Paper；不同版本独立。

```json
{
  "id": "12c45b4d-01db-4e7b-88dd-9a03ba749ff1",
  "provider": "arxiv",
  "external_id": "1706.03762v7",
  "attempt": 1,
  "status": "queued",
  "paper_id": null,
  "paper_status": null,
  "error": null,
  "created_at": "2026-11-12T18:00:00Z",
  "updated_at": "2026-11-12T18:00:00Z",
  "started_at": null,
  "finished_at": null
}
```

仅 succeeded 有 paper_id；paper_status 是关联 Paper 当前状态。下载成功/解析失败仍 Import succeeded、Paper failed；错误由 Paper 详情获取，禁止用导入重试覆盖文件。内部 worker/lease/路径不公开。

### GET /api/v1/paper-imports

limit 默认 20/范围 1—100，offset 默认 0/非负，可选 status。返回 Page<PaperImport>，created_at DESC/id DESC；供刷新后恢复。

### GET /api/v1/paper-imports/{import_id}

200 为 PaperImport；不存在返回 404 PAPER_IMPORT_NOT_FOUND。

### POST /api/v1/paper-imports/{import_id}/retry

请求 `{"expected_attempt":1}`，必须严格正整数，不接受 bool/额外字段。

- failed、attempt 匹配且 error.details.retryable=true：原子 attempt+1，清除旧执行信息回 queued，202。
- 已是 expected_attempt+1：重放当前记录，queued/running 为 202、终态为 200；即使已再次失败也不重入队。
- 其他冲突 409 IMPORT_RETRY_CONFLICT；非可重试失败 409 IMPORT_NOT_RETRYABLE；不存在 404。
- 不修改研究 Task 重试规则；Worker 不自动重试网络或失效执行。

### 10.2 配置、错误与轮询

ARXIV_ENABLED 默认 false，启用必须配置 ARXIV_CONTACT_EMAIL。搜索/新提交/重试未启用或配置不全返回 503 ARXIV_NOT_CONFIGURED；历史导入/论文读取不依赖上游。

| 情况 | HTTP / code |
| --- | --- |
| 输入不合法 | 422 INVALID_REQUEST |
| 共享许可忙碌/上游限流 | 429 ARXIV_RATE_LIMITED |
| 上游网络/服务失败 | 502 ARXIV_UNAVAILABLE |
| 非法上游响应 | 502 ARXIV_INVALID_RESPONSE |
| 搜索总超时 | 504 ARXIV_TIMEOUT |

HTTP 错误沿用第 8 节 envelope；429 带整数秒 Retry-After 和相同 details.retry_after_seconds，不自动循环请求。

搜索和指定版本元数据请求仍受 20 秒整体时限约束。其读取等待最多 15 秒，连接/写入/连接池等待最多 5 秒，各阶段同时受剩余预算限制；较长读取等待不会延长父监督或子进程 watchdog 的总时限。PDF 下载各阶段仍最多 5 秒，总预算仍为 90 秒。共享许可、完成后冷却、Retry-After 和无自动重试规则保持不变。

搜索来源失败时，服务端以请求对应的 `X-Request-ID` 记录 `phase`、`elapsed_ms` 和安全错误码；阶段限定为连接、写入、连接池、响应头、响应体、总时限、共享许可、来源 HTTP 状态、响应校验或未知，不记录检索词、联系邮箱、原始异常、响应正文或凭据。该诊断仅用于服务端日志，不添加到公开错误字段；watchdog 退出明确按总时限超时处理。

前端可保留当前页面上一份成功结果，必须同时标注其原关键词、页码和接收时间，并在新请求未完成时说明尚未更新，不得将旧结果冒充新结果。重试重复失败请求的原关键词/offset；旧结果翻页使用其原关键词。`ARXIV_TIMEOUT` 后有 5 秒页面级手动搜索等待，不自动重试，不影响导入/历史读取；它不替代后端共享许可，也不承诺来源恢复时间。429 的服务端冷却规则不变。结果快照不跨刷新持久化，成功空结果会替换旧结果，导入历史仍由服务器保存。

已接收导入的执行失败返回 status=failed/error：ARXIV_NOT_FOUND、ARXIV_VERSION_MISMATCH、ARXIV_RATE_LIMITED、ARXIV_UNAVAILABLE、ARXIV_INVALID_RESPONSE、ARXIV_TIMEOUT、UNSAFE_SOURCE_URL、FILE_TOO_LARGE、INVALID_PDF、STORAGE_WRITE_FAILED、IMPORT_TIMEOUT、IMPORT_LEASE_EXPIRED、IMPORT_WORKER_STOPPED。details.retryable 必须为 boolean：暂时网络/服务/限流/超时/存储及 Worker 中断 true；不存在/版本不符/非法响应/不安全 URL/超限/非法 PDF false。错误不回显上游正文或内部路径。

前端对 queued/running 每 2 秒轮询，终态停止；成功后跟踪 Paper 解析。失败仅 retryable=true 可重试。元数据作为纯文本显示，真正 ready 才允许真实研究任务。
