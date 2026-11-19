# Literature Research Agent Assistant — API 契约

版本：v1 · 更新日期：2026-11-14。账号契约与集成/验收边界见第 11 节；以下既有业务验收记录保留其原证据范围。已实现 API/Mock Worker、独立 PDF Parser、真实摘要/问答 Runner、多论文综述及第 10 节 arXiv 搜索/导入接口。用户已完成 MVP-3 的隔离原生 PostgreSQL 八组专项验收、真实 arXiv 单版本搜索/下载/解析及浏览器 Mock 任务闭环；另已完成一次 DeepSeek 真实单篇摘要及人工引用/刷新核验，真实问答与多论文综述仍待验收。详细证据范围见实施记录；启动方式见 `backend/README.md`。

需求依据：`docs/Proposal.md` 第 2、3 节。数据库设计见 `docs/database-design.md`，参考 DDL 见 `backend/sql/schema.sql`。

## 1. 基本约定与范围

- 业务前缀 `/api/v1`；开发默认 origin 为 `http://localhost:8000`；`/health`、`/ready` 不带前缀。
- 账号采用用户名/密码和强制邮箱验证，业务接口以 Cookie 会话和服务端用户归属隔离；账号路由/CORS/归属及配额检查已实现，本次实施已验证原生账号与所有权链路通过，真实 SMTP 配置/投递验收待完成，详见第 11 节。
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
| budget_mode | string | automatic 为新建任务的后端自动分配，manual 仅用于历史手动预算任务 |
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

终态不可回退，终态重试创建新任务。新分阶段综述在租约失效时允许 running → queued，在原截止时间内恢复；历史任务失联仍失败。queued → failed 也用于恢复等待期间耗尽执行时限。Worker 使用数据库租约并拒绝失去所有权的写入；超时、预算耗尽和不可恢复异常变为明确的 failed。

阶段示例：analyzing、synthesizing、validating、queued、mock_preparing、mock_generating、mock_completed、parsing、searching、retrieving、writing、checking、completed、failed。客户端容忍新增阶段；只有 status 决定是否停止轮询。

**Budget：**

| 字段 | 兼容请求的默认值 | 可接受范围 |
| --- | --- | --- |
| max_steps | 10 | 1—100 |
| max_tokens | 8000 | 1—100000 |
| timeout_seconds | 120 | 1—1800 |

新建 summary/qa/review（含 Mock）统一由后端计算预算，前端不发送 budget。该字段仅为旧客户端及历史幂等重放保留，可省略或只提供部分字段，schema 仍校验范围，但合法值不控制新任务执行。响应 budget 为实际冻结值，不采用表中的兼容默认值。max_tokens 是任务累计输入与输出 Token 上限，另检查单次上下文；超时从首次执行开始，初始排队不计入。Mock 不产生模型用量。

**TaskStats：**

- queue_ms = started_at − created_at，未开始为 null。
- execution_ms = finished_at − started_at，未开始或未结束为 null。
- end_to_end_ms = finished_at − created_at，未结束为 null。
- input_tokens、output_tokens、model_calls、tool_calls 为非负整数或 null。
- total_tokens 仅在输入、输出均已知时返回二者之和，否则为 null。
- usage_estimated 为 boolean；新分阶段综述如包含尚未确认或缺少完整 usage 的调用，则为 true，Token 统计含保留的预留值；其他任务默认为 false。

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

### DELETE /api/v1/papers/{paper_id}

需要当前账号、同源 Origin 和 X-CSRF-Token。成功返回 204，无响应体。锁定论文后检查任意 TaskPaper 引用；有引用返回 409 PAPER_IN_USE，解析中返回 409 PAPER_PROCESSING。其他账号或不存在的论文返回 404 PAPER_NOT_FOUND。

删除事务清理该论文的导入映射、来源、解析片段及论文记录；提交后清理受控 PDF 文件。研究任务和历史引用不删除。arXiv 搜索的来源元数据缓存不受影响，每次搜索仍实时叠加当前账号的导入状态；删除后返回未导入，可再次导入新记录。

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
  "workflow_type": "baseline"
}
```

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| task_type | 是 | summary、qa 或 review |
| question | 条件必填 | 去首尾空白；qa/review 为 1—8000 字符；summary 可省略或为 null，空白归一为 null，非空时同样为 1—8000 字符；超长返回 422 INVALID_REQUEST |
| paper_ids | 是 | summary/qa 恰好 1 篇；review 为 2—20 篇；UUID 不得重复 |
| workflow_type | 否 | 默认 baseline，MVP-0 不开放 extended |
| budget | 否 | 兼容旧客户端；新任务统一忽略合法值，由后端动态分配。非法值仍返回 422 |

paper_ids 视为集合，转 UUID 标准字符串后排序。不存在论文返回 404，details.missing_paper_ids 列出缺失 ID。Mock 允许 uploaded/ready，processing/failed 返回 409 PAPER_NOT_READY；真实 Runner 只允许 ready。真实模式需配置 `LLM_BASE_URL`、`LLM_MODEL_ID` 和 `LLM_API_KEY`；缺少任一项时返回 `503 RUNNER_NOT_CONFIGURED`，不创建任务且不降级为 Mock。真实模式支持 summary、qa 及 review；review 要求全部 2—20 篇论文 ready。

runner_type、is_mock、model_id、status、stage、thread_id 及存储配置均不接受客户端写入。后端冻结 Runner、工作流版本和模型等执行配置，后续配置变更不能改变已提交任务。

历史 langgraph-review-v1 真实 review 后期提交时由服务端冻结内部 `run_config.max_output_tokens=4096`，该字段不是客户端请求参数，不增加公开任务/产物字段。模型单次输出上限为冻结值与剩余预估总 Token 预算的较小值；预估输入已耗尽总预算时不调用模型。旧任务缺少字段时保持 2048，含既有 review-v2；历史 summary/qa 保持 2048，Mock 不变。持久化值仅允许精确整数（review 为 2048/4096，历史单篇为 2048），非法配置在调用前失败。实际用量仍受原总预算约束，时间预算、单次调用、严格引用与原子写入不变；4096 不保证完整输出，不自动重试/续写或修复 JSON。重建任务是新提交；旧任务和原幂等键的重放不升级输出上限。

新建真实 summary/qa 使用自动策略 `single-auto-v1`，工作流仍为 `langgraph-v1`，提示版本仍为 `evidence-v4`。创建时按证据规模、问题长度及完整提示 UTF-8 字节数加 512 开销估算输入，冻结选定证据和资源。动态输出以 256 Token 为单位，受 RESEARCH_OUTPUT_TOKENS（默认 8192）限制；上下文受 RESEARCH_CONTEXT_TOKENS（32768）限制，总量含额外 512 余量且受 RESEARCH_TASK_TOKENS（100000）限制。不能容纳时缩减证据，仍不足返回 `422 RESEARCH_CAPACITY_EXCEEDED`，不创建任务或调用模型。单次调用期限随输入/输出估算增长，最大 RESEARCH_CALL_TIMEOUT_SECONDS（180 秒，允许 5—300）；任务总期限另加 30 秒余量，最多一次模型调用。空匹配证据直接返回证据不足，不调用模型。旧任务保留原输入、2048 输出上限和旧超时；重放不升级策略。Mock 新任务自动使用两步、1 Token 占位上限（实际模型用量为零）和至少 30 秒执行期限。自动预算不保证 JSON 永不截断，不增加自动重试、续写或放松引用校验。

新建真实 summary/qa 任务的 versions.prompt_version 为 `evidence-v4`。后端从已选存储片段生成最长 1000 字符的连续证据摘录，保留内部排版与 Unicode，不跨片段或物理页码，并分配任务内 evidence_id。内部模型结果按 paragraphs 返回每段正文与 evidence_ids，后端解析 ID、取原样引文与来源身份、按首次使用顺序分配引用编号，再执行原有严格来源、逐字引文及大小校验。跨段同一证据共享编号；未知 ID、同段重复 ID、模型自写引用标记或额外引文/来源字段会失败，不进行模糊匹配或静默替换。paragraphs/evidence_ids 不是对外 API 字段，产物仍返回 content_markdown 与 citations。

历史 langgraph-review-v1 review 的 versions.prompt_version 后期为 `evidence-review-v2`，workflow_version 仍为 `langgraph-review-v1`。输入沿用原样证据摘录并标明所属 paper_id，evidence_id 在任务内唯一。内部模型返回 paragraphs 和 comparison_table；段落包含 content_markdown/evidence_ids，表格单元格包含 value/evidence_ids，不接收模型自报引文、页码或引用编号。后端先按段落、再按选定论文和声明列顺序解析 ID，跨正文与表格共享首次使用编号，允许仅在表格使用的引用。非 null 研究单元格必须引用本行论文；null 必须使用空 evidence_ids。未知 ID、同段/同单元格重复证据、跨论文单元格引用、模型自写引用标记或额外字段均会失败。后端生成原协议草稿后仍执行既有严格综述校验，外部 content_markdown/citations/comparison_table 结构不变。

Runner 按已保存版本构造提示词、估算输入预算并选择解析器；历史 `evidence-v1`/`evidence-v2`/`evidence-v3` 和 `evidence-review-v1` 任务仍使用原提示词和严格校验，未使用引用或非逐字引文仍导致失败；缺少提示版本的旧 review 回退至 v1。版本由服务端决定，不接受客户端指定；幂等重放返回原任务，不切换版本。这些历史版本不增加模型调用或自动重试；失败时不发布产物。

服务端可选 `LLM_THINKING_MODE=provider_default|disabled|enabled`，随真实任务冻结为 run_config.model_thinking_mode；不接受客户端指定。provider_default 不向模型发送 thinking 字段，另外两项发送对应 thinking.type，仅适用于支持该扩展的服务。旧任务缺少字段时使用 provider_default；不改变现有 Token/时间预算或引用校验。

新建真实综述使用 `langgraph-review-v2 / evidence-review-v3`：客户端可省略 budget；即使提供合法 budget 也由服务端自动规划覆盖，响应 `budget_mode=automatic` 和 budget 为冻结后的实际分配。非法 budget 仍由请求 schema 拒绝。按论文数量、问题、采样证据及提示词长度，在 100 次调用、100000 累计 Token、1800 秒硬上限内选择配置；不能容纳返回 `422 REVIEW_CAPACITY_EXCEEDED`，不会请求模型。论文数量允许 2—20 不代表任意二十篇必定能容纳。

工作流逐篇生成四列分析，再生成三个短章节，最后由后端组装比较表和引文。综合请求仅包含当前章节相关的已验证分析与其原始证据摘录；不一次生成整个产物。每篇最多四个原样片段，按冻结配置每篇额度 1000—4000 字符；支持不足的内容为 null。输入按 UTF-8 字节加消息开销预留；分析文本同时受字符和 JSON 序列化字节上限约束。单次上下文/输出限制由服务器配置，不能从前端修改。

单元最多两次尝试；全任务额外重试不超过两次（13—20 篇最多一次），覆盖无效 JSON、长度截断、证据校验失败和模型请求失败，只重试当前单元。所有尝试均累计 usage 或保守预留；成功结果与实际 usage 在同一事务保存。失联恢复复用已验证单元；原截止时间、失败/不确定调用预留不清零。仅全部校验通过后原子发布公开 Artifact，产物 schema 不变，仍保留逐字引文、论文归属、页码和引用完整性校验。

analyzing / synthesizing 的 stage 事件 payload 为 `{unit, current, total, paper_id?}`，用于中英文进度；validating 表示最终校验。未知阶段不影响按 status 判终态。历史任务/幂等键重放维持原版本和原预算哈希；新自动预算任务的预算差异不构成不同提交。summary、qa 和 Mock 执行行为不变。


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
- `20261114_0004` 起幂等键按当前用户唯一：`(user_id,idempotency_key)`；不同用户的同键独立，业务请求不接收 user_id。不自动过期或复用键。
- request_hash 对规范化后的 task_type、question、排序的 paper_ids、workflow_type 计算 SHA-256；所有新任务移除 budget。历史手动任务按原规则包含补齐默认值的 budget。重放先读取任务的冻结预算模式，再使用对应哈希规则，既不重算资源也不消耗新任务配额；JSON 使用 UTF-8、递归按键排序、无多余空格、不转义非 ASCII 字符。
- 同键同哈希返回原任务，仍为 202，Idempotency-Replayed 响应头为 true；新任务为 false。
- 同键不同哈希返回 `409 IDEMPOTENCY_CONFLICT`；并发由数据库唯一约束及冲突后重查保证只创建一项。
- 请求规范化后先在当前用户范围查幂等键；同请求重放不重新检查论文当前状态，首次提交仍完整校验全部论文归属和状态。
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

历史 langgraph-review-v1 review 的总上下文最多 32 个存储片段，并受冻结的 evidence_context_chars 限制；v2 可将单个存储片段划分为多条不跨页的原样摘录，32 限制针对存储片段而非摘录条数。为每篇有片段论文至少预留一个最短片段，不足时任务以 BUDGET_EXCEEDED 失败且不调用模型。所有选定论文均无片段时，服务端返回证据不足正文与 evidence_status（证据状态）单列比较表，每行值为“未检索到可用解析证据”，无引用；该系统状态不是研究结论，允许非 null 且无引用。此路径 input_tokens、output_tokens、total_tokens、model_calls、tool_calls 均为 0。历史 review 使用 langgraph-review-v1/evidence-review-v2，旧任务保留 v1；表格按任务冻结的选定顺序排列，部分无证据论文的研究内容 cell 必须为 null。

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
| 401 | AUTH_REQUIRED | 未登录、会话过期/撤销或账号不可用 |
| 403 | ORIGIN_REJECTED / CSRF_REJECTED | 来源或会话 CSRF 校验失败 |
| 404 | PAPER_NOT_FOUND / TASK_NOT_FOUND | 资源不存在或不属于当前用户 |
| 409 | PAPER_NOT_READY | 论文状态不允许执行 |
| 409 | IDEMPOTENCY_CONFLICT | 幂等键已绑定不同请求 |
| 413 | FILE_TOO_LARGE | 文件超过 20 MiB |
| 415 | UNSUPPORTED_MEDIA_TYPE | 上传请求不是 multipart |
| 422 | INVALID_REQUEST | 缺字段、非法 UUID/枚举、数量、重复 ID、预算、未知字段等 |
| 422 | REVIEW_CAPACITY_EXCEEDED | 综述在服务器上下文、累计 Token 或时间上限内无法规划，减少论文或缩短问题 |
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

q 必填，规范化后 1—200 字符/最多 20 词，普通关键词而非原始高级语法。limit 默认 10/范围 1—50；offset 默认 0/范围 0—1000。不接受上游 URL/provider。

排序参数：sort_by 为 relevance（相关度，默认）、submittedDate（首次发布时间）或 lastUpdatedDate（来源最后更新时间）；sort_order 为 descending（默认）或 ascending。排序由来源对完整检索结果执行，无效枚举返回 422。前端每页条数可选 10、25、50，默认 10；切换条数或排序时回到第一页并保留其他检索条件。页码跳转按实际每页条数计算 offset；在 offset≤1000 的边界下，三种条数分别最多浏览 101、41、21 页。请求失败时保留上一批结果及其真实页码、条数。

200：`{items: SearchPaper[], total: number, limit: number, offset: number}`。SearchPaper 为 PaperSource 加可空 import_id/import_status/paper_id/paper_status。import_status 为 queued/running/succeeded/failed；paper_status 为既有 PaperStatus。total 是上游本次报告，不保证跨页快照。

成功上游数据缓存 600 秒/每进程最多 100 页，缓存键包含规范化关键词、limit、offset、sort_by 和 sort_order；不同排序互不复用结果。本地导入/解析投影每次重查。无匹配返回空数组和 total=0；offset 越过结果末尾时 items=[]，但保留上游 total。上游错误不能伪装空结果。

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

- failed、attempt 匹配：原子 attempt+1，清除旧执行信息回 queued，202。
- 已是 expected_attempt+1：重放当前记录，queued/running 为 202、终态为 200；即使已再次失败也不重入队。
- 其他冲突 409 IMPORT_RETRY_CONFLICT；不存在 404。所有下载失败均允许用户手动重试，仍受账号导入额度和 expected_attempt 约束。
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

前端在新搜索或翻页等待期间可暂留上一份成功结果；搜索请求失败后清空搜索状态和旧结果，以弹窗显示错误原因及请求编号，不再展示上次成功结果。站内切换可保留成功搜索状态和进行中的请求，但刷新、新页面或退出账号后清空。手动清除搜索会取消当前查询并忽略迟到响应。`ARXIV_TIMEOUT` 后仍有 5 秒手动搜索等待，429 仍按服务端 Retry-After 限制；清空搜索不解除冷却，也不自动重试。搜索失败不影响已经提交的导入或论文库。

已接收导入的执行失败返回 status=failed/error：ARXIV_NOT_FOUND、ARXIV_VERSION_MISMATCH、ARXIV_RATE_LIMITED、ARXIV_UNAVAILABLE、ARXIV_INVALID_RESPONSE、ARXIV_TIMEOUT、UNSAFE_SOURCE_URL、FILE_TOO_LARGE、INVALID_PDF、STORAGE_WRITE_FAILED、IMPORT_TIMEOUT、IMPORT_LEASE_EXPIRED、IMPORT_WORKER_STOPPED。details.retryable 必须为 boolean：暂时网络/服务/限流/超时/存储及 Worker 中断 true；不存在/版本不符/非法响应/不安全 URL/超限/非法 PDF false。错误不回显上游正文或内部路径。

前端对 queued/running 每 2 秒轮询，终态停止；成功后跟踪 Paper 解析。失败记录均提供手动重新下载；details.retryable 仅记录错误分类，不再作为手动重试门禁。元数据作为纯文本显示，真正 ready 才允许真实研究任务。

## 11. 账号、会话与资源归属（2026-11-14）

本节依据当前导出的 `backend/src/app/auth/api.py`、service/security/dependencies 及 `20261114_0004` 记录账号契约。当前主应用已实现账号路由、带凭据 CORS 和私有缓存中间件，业务层已实现所有权/配额检查。2026-11-14 本次实施已验证：原生所有权 16 项（含 schema.sql/ORM 对照）、账号原生 harness 74 项（无跳过）、原生综述 8 项全部通过；默认 discover 共 124 项，68 项通过、56 项环境门控跳过，门控套件已另行原生执行通过。实际账号 API 完整注册/验证/登录/上传/找回/重置/撤销链路、本地账号配置校验，以及前端构建/隔离浏览器重跑均通过。实际配置数据库 head=20261114_0004、无漂移，业务记录/用户/生成文件均为 0，source gate seed 为 1。真实 QQ SMTP 与邮件端到端验收待执行，设置和独立邮件进程见 `backend/README.md` 第 10 节。

### 11.1 输入、响应与状态

前缀 `/api/v1/auth`。所有 POST 必须为 `application/json`，Origin 必须精确匹配 `FRONTEND_PUBLIC_URL`（去掉末尾 `/`）；浏览器自动提供 Origin，不由脚本伪造。账号 POST 请求体上限 16 KiB，未知字段或非法字段返回脱敏 `422 INVALID_REQUEST`，不回显密码/令牌。登录以用户名进行，邮箱只用于验证和找回，不作登录名。

| 方法与路径 | JSON 输入 | 成功响应 | 会话要求 |
| --- | --- | --- | --- |
| POST /register | `{username,email,password}` | `202 {"accepted":true}` | 公开；创建 pending 账号和验证 outbox |
| POST /verify-email | `{token,password}` | `200 {"ok":true}` | 公开；password 必须为注册时原密码；验证后另行登录 |
| POST /resend-verification | `{email}` | `202 {"accepted":true}` | 公开；不透露邮箱存在、状态或投递结果 |
| POST /forgot-password | `{email}` | `202 {"accepted":true}` | 公开；不透露邮箱存在、状态或投递结果 |
| POST /login | `{username,password}` | `200 {user:{id,username,email},csrf_token}`，附 Set-Cookie | 公开；仅允许 active 且已验证的账号 |
| GET /me | 无 | `200 {user:{id,username,email},csrf_token}` | Cookie |
| POST /logout | `{}`，无业务字段 | `200 {"ok":true}`，清除 Cookie | Cookie + CSRF；仅撤销当前会话 |
| POST /reset-password | `{token,password}` | `200 {"ok":true}`，清除 Cookie | 公开；password 是新密码，撤销所有会话 |
| POST /change-password | `{current_password,password}` | `200 {"ok":true}`，清除 Cookie | Cookie + CSRF；验证当前密码，撤销所有会话 |

注册/重发/忘记密码的 202 只表示请求受理，不表示 SMTP 已投递；用户名/邮箱冲突注册统一 `409 REGISTRATION_UNAVAILABLE`，不区分冲突字段。忘记密码对不存在、未验证或停用账号同样返回通用 202；格式错误、限流和服务配置错误仍可分别返回 422/429/503。错误凭据统一 `401 INVALID_CREDENTIALS`；仅在用户名密码正确但尚未验证时返回 `403 EMAIL_NOT_VERIFIED`。

- 注册用户名去除首尾空白后为 3—32 个 ASCII 字母、数字或下划线，唯一键按小写处理；保留名 `admin`、`administrator`、`root`、`system`、`support`、`api`、`auth`、`postmaster`、`abuse` 不可注册。
- 邮箱去首尾空白，当前服务接受最长 254 字符的 ASCII 本地部分和 DNS 域名格式（本地部分至多 64 字符），域名至少含一个点；完整邮箱按小写唯一，不折叠点或 `+` 后缀。数据库容量 320 不代表接口允许 320 字符。
- 注册/新密码及验证原密码为 6—128 个 Unicode 字符，须为有效 UTF-8；不 trim、不强制字符种类。登录和 change-password 的 current_password 输入模型允许 1—128 字符；有效新建账号密码仍须满足 6—128。密码使用 Argon2id 存储。确认密码仅由前端验证，不提交额外字段。
- 邮件 token 输入为 32—256 字符；实际发放为 32 随机字节的 URL-safe token，仅将 SHA-256 摘要保存到 token/session 表。验证与重置用途不可互换，消费/过期/撤销后统一 `400 AUTH_TOKEN_INVALID`；验证原密码错误也使用同一错误。
- 验证 TTL 默认 24 小时、重置默认 30 分钟、会话默认 7 天。重发撤销同用途旧 token 和未完成邮件，不延长 pending 注册后的 24 小时总窗口。令牌消费锁定用户和 token，避免并发重复使用。

### 11.2 Cookie、Origin、CSRF 与缓存

生产会话 Cookie `__Host-lra_session`：Secure、HttpOnly、SameSite=Lax、Path=/、无 Domain；`AUTH_COOKIE_SECURE=true` 同时要求 HTTPS 前端 origin。本机 HTTP loopback 专用 `lra_dev_session`，其余属性相同但无 Secure。Cookie 的 Max-Age 来自 `AUTH_SESSION_TTL_SECONDS`，服务端仍检查用户 active、会话过期/revoked 和 auth_version。返回 JSON 不含原始会话 token；不得将认证 Cookie 改为 localStorage 中的 Bearer token。

跨端口请求使用 `withCredentials: true` 或 `credentials: "include"`。CORS 允许明确前端 origin 与 credentials，预检须允许 Content-Type、Idempotency-Key、X-CSRF-Token，禁止通配 origin。所有账号 POST（包括公开注册、登录、重置）检查 Origin 与 JSON；其中 logout/change-password 另验证会话及 `X-CSRF-Token`。所有已认证业务写入（含 multipart 上传、任务提交、导入和重试）也必须带当前会话 CSRF 和匹配 Origin，不能因为不是 JSON 而跳过 CSRF。

CSRF 从 login/me 响应读取并仅存内存，按独立密钥与当前会话绑定；更换会话后重新读取。缺失/错误 Origin 返回 `403 ORIGIN_REJECTED`，缺失/错误 CSRF 返回 `403 CSRF_REJECTED`。这两类错误不能解释为账号不存在。已认证业务请求收到 401 才按会话失效处理；公开登录/重置等有意产生的 401 在当前页面显示，不能触发全局重定向循环。

全部 `/api/v1/` 响应（包括私有 PDF、错误响应）应设置 `Cache-Control: no-store`、`Pragma: no-cache` 和 `Referrer-Policy: no-referrer`。鉴权下载通过受控 API 校验所有权，不开放 uploads 静态文件路径。`/health`、`/ready` 保持匿名，只返回健康状态/脱敏就绪错误；数据库 ready 不等于账号密钥、SMTP 或外部模型可用。

### 11.3 邮件与浏览器生命周期

服务端从可信 FRONTEND_PUBLIC_URL 生成 `/verify-email#token=...` 和 `/reset-password#token=...`；不接收客户端指定回跳域名、不使用查询字符串放 token。前端只解析 fragment 一次并立即清理地址栏，在内存中保留待显式提交的 token；打开链接不自动验证/重置，不向第三方资源转发 token。`Accept-Language` 首语言以 zh 开头选择中文邮件，其余选择英文。

注册需要密码确认；pending 页面说明检查邮件、使用原密码验证，并允许重新发送。验证成功返回登录页；重置/改密成功后所有设备重新登录。API 原子写入用户/token/加密 outbox，独立 `python -m app.mail_worker` 负责 QQ SSL465 投递；sent/failed 清空加密载荷，最多三次投递尝试，不在 API 请求内同步发信。账号 API 生命周期已通过上述验证；真实 SMTP 配置、实际中英文邮件收信及邮件链接端到端验收仍待完成，不能将 202、mock 或测试视为真实送达。

受保护研究路由等待 me 结束再展示；未登录保存安全的站内路径，拒绝外部 URL、双斜杠、反斜杠、控制字符及编码绕过。账户菜单显示服务端用户名，并提供改密和退出。退出、业务 401 或跨标签身份变化必须取消旧请求/轮询，使迟到响应、旧幂等提交与私有状态失效，按新身份重新挂载研究子树；仅语言偏好保留。

### 11.4 所有权、错误与验收边界

论文、PDF、任务、事件、产物、引用、导入记录和重试均以服务端会话用户限定；业务输入不增加 user_id，客户端提供的 ID 也必须与当前用户所有权一起查询。未认证返回 `401 AUTH_REQUIRED`；其他账号资源与不存在资源统一 404，不返回其标题或状态。选择多篇论文时全部须属同一当前用户。

任务幂等唯一键为 `(user_id,idempotency_key)`；arXiv Source/Import 唯一键为 `(user_id,provider,external_id)`。不同用户可使用相同键或导入相同版本，私有论文、导入和结果不共享。上游访问 gate/成功元数据缓存仍共享，但本地导入状态须按当前用户重新投影。USER_ACTIVE_TASKS、USER_ACTIVE_IMPORTS、USER_DAILY_TASKS 默认 2、2、20；服务层锁定当前用户行，统计 queued/running 任务或导入、UTC 当日创建任务后决定是否接受新工作（含导入重试）。超限分别为 `429 TASK_CAPACITY_EXCEEDED / IMPORT_CAPACITY_EXCEEDED / DAILY_TASK_LIMIT`，Retry-After 分别为 30/30/3600 秒；原生所有权测试已在本次实施验证通过；审查发现的重置后共享 gate 缺失已修复，reset 后许可领取/释放已有正向回归。导入完成/重试的锁冲突已修复：用户配额采用 FOR NO KEY UPDATE，兼容外键引用锁；原生交叠回归通过，详见 backend/README.md 第 10.6 节。配额中文消息及对应英文诊断映射已补齐，错误码及 Retry-After 契约保持不变。原任务幂等重放不消耗新配额。自动综述预算和旧任务冻结配置规则保持原契约。

账号补充错误：`400 AUTH_TOKEN_INVALID`、`401 AUTH_REQUIRED / INVALID_CREDENTIALS`、`403 EMAIL_NOT_VERIFIED / ORIGIN_REJECTED / CSRF_REJECTED`、`409 REGISTRATION_UNAVAILABLE`、`413 REQUEST_TOO_LARGE`、`415 JSON_REQUIRED`、`429 AUTH_RATE_LIMITED`（附 Retry-After 秒数）、`503 AUTH_UNAVAILABLE`；统一使用第 8 节 Error 结构，不回显输入密码、token、Cookie、邮箱是否存在或原始 SMTP 异常。

代码静态对照：前后端 endpoint、字段名、login/me 响应和凭据/CSRF 发送一致；logout/reset/change 实际返回 200 JSON，前端忽略响应体，兼容。当前前端 email 正则比后端宽松，未同步 ASCII/254 字符及保留用户名校验；登录/当前密码前端要求 6—128，后端模型允许 1—128（正常新账号不受影响）。前端验证文案固定 24 小时，而后端验证 TTL 可缩短；这些属于非阻断的预校验/文案差异，服务端仍执行完整规则；当前验收使用默认 24 小时时效和符合完整规则的输入。

## 12. 跨语言研究检索（2026-11-15）

新建真实 summary / qa / review 任务使用 workflow_version=langgraph-search-v1。单篇内部协议为 evidence-search-v1，综述为 evidence-review-search-v1；旧工作流按旧路径读取，历史结果不自动重跑。任务创建只执行本地规划，原有请求字段与自动预算规则不变。

创建任务时将当前用户选定论文的完整解析片段、论文标题、文件哈希和 parser_version 存入 source_snapshot，并校验 SHA-256；默认序列化上限 8 MiB，可由 RETRIEVAL_SNAPSHOT_BYTES 配置。超过上限或不能为检索/生成预留资源时，在创建前返回 422 RESEARCH_CAPACITY_EXCEEDED 或 REVIEW_CAPACITY_EXCEEDED。快照、扩展查询和全文不通过任务详情接口返回。

Worker 对含中文的问题最多调用一次查询扩展：1—3 个英文表达、每个最长 160 字符、输出至多 512 Token、超时至多 15 秒。扩展失败时记录 warning 并使用原问题、内置术语与论文结构继续。检索合并原问题与扩展表达，过滤英文停用词，按词面相关性和结构覆盖选择逐字连续原文；零命中仍提供上下文，不能直接断言全文无答案。摘要覆盖结构与问题；新摘要和问答允许一次补检索，综述逐篇覆盖并允许每篇一次补检索。所有模型尝试（包括未知结果和恢复尝试）计入服务器预算。生成、校验失败的重试额度也受任务总量限制。

任务详情新增可空 retrieval 字段：旧任务/Mock 为 null；新任务包含 status、expansion_degraded、selected_chunks、lexical_matches、missing_aspects、papers。status 为 pending / matched / context_fallback / no_parsed_text / answered / partial / insufficient_selected_evidence。selected_chunks 和 lexical_matches 表示初次选证据情况，不能当作事实置信度；补检索数量见事件 payload.new_chunks。missing_aspects 为模型报告的单篇未覆盖问题；papers 为综述缺口数组，每项包含 paper_id、paper_title（提交时冻结的标题）、columns（缺失维度标签），仅返回本任务选中的论文，省略没有缺口的论文。历史检查点没有逐篇缺口时默认为空数组。

证据覆盖后续改进：新摘要与问答都为一次补检索预留服务器预算；旧摘要没有 supplement_rounds 标记时不追加调用。补检索优先使用缺失项与内置中英术语，可选取已读原片段中的另一连续窗口。两次部分单篇回答合并有据段落；综述补检只填原空单元格，保留已有结论和引用。补检仍未覆盖时显示具体缺口，不能保证问题一定可回答。无需新数据库迁移，重启 API 与 Runner 后创建新任务。

retrieving 阶段的事件可带 retrieval、retrieval_status、reason、paper_id、new_chunks、evidence_status 等诊断字段。前端必须区分无解析文本、当前证据不足、部分可回答；比较表 null 显示“当前证据未覆盖”，不能据此断言论文未报告。输出仍使用原 Artifact / Citation 结构，引用 ID 由后端解析为冻结原文及物理页码。

新工作流使用与综述相同的租约和持久化调用预留。租约过期可重新排队，保留原 started_at 和截止时间；已完成查询、选证据、分析和输出检查点复用。未知模型调用按预留用量保守保留；查询扩展未知结果不重复发起，生成可在有剩余额度时恢复。迁移 20261115_0005 只扩展 tasks_lifecycle 约束，不删除数据。

### 导入来源快照（2026-11-18）

`paper-imports` 的新建/重试请求体保持不变，不接受客户端提供元数据。服务端可从未过期的搜索缓存查找完全相同版本的已验证元数据，并内部持久化到 `PaperImport.source_metadata`；该字段不出现在公开响应中。Worker 重新校验结构和版本后复用，缺失时回退到原有元数据 API 查询。PDF 仍独立下载、校验和落盘，不把元数据缓存当成 PDF 下载完成。

### DELETE /api/v1/tasks/{task_id}（2026-11-19）

需要账号会话、同源 Origin 和 X-CSRF-Token。仅可删除当前账号的研究记录，成功返回 204。不存在或属于其他账号返回 404 TASK_NOT_FOUND；运行中返回 409 TASK_RUNNING。先锁定任务行，再检查状态，防止与 Worker 领取竞争。

使用既有数据库级联删除研究结果、证据引用、执行事件和 task_papers 关联，不删除原论文。论文只有在不再被任何任务引用且不处于解析中时才允许删除；同一论文仍被其他任务引用时继续返回 PAPER_IN_USE。无新增数据库迁移。
