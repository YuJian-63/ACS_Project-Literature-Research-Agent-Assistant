# 前端 Agent 适配待办与统一修改方案

初始核对日期：2026-11-19，基线 `3b45291`，分支 `backend-dev-v2`。2026-11-20 已将 main（`bd67fbe`）前端更新合入本分支，并完成下述接口兼容修复。当前派发只开放 baseline，extension 检索入口仍待后续接入。

**状态：部分完成，以下进展优先于原待办描述。** 已补齐 Task/Artifact/Citation 的兼容展示字段、部分完成状态和未解决项提示、Markdown 比较表及其引用/PDF 返回导航。同步修复失败远端作业删除保护、DELETE 预检和公网 HTTP 下的 UUID 生成；新任务回答语言跟随提问，摘要无关注点时默认中文。原生失败结果展示、能力查询及扩展检索仍待实施；本次无需数据库迁移，离线测试不代表真实 TACC 验收已通过。

## 1. 目标与前置条件

后端和独立 Agent 已完成第 3.1–3.3 阶段的本地/TACC 传输、恢复与维护实现，页面目前主要使用旧版兼容接口。下一阶段需要让摘要、问答和跨论文综述正确呈现 Agent 的执行状态、原生结果、未解决项和引用，并保留已有 PDF 阅读体验。

先按 [传输统一验收清单](agent-transport-acceptance.md) 验证数据库、本地真实模型及 TACC 链路，再开展面向真实部署的前端联调。离线页面开发和夹具测试可以提前进行，但不能因此标记真实部署验收完成。

相关资料：

- [后端与独立 Agent 对接](agent-backend-integration.md)：当前职责、限制和恢复语义。
- [API 契约](api-contract.md)：已实现的任务、事件、结果和引用接口。
- [终端操作手册](terminal-operations.md)：Windows/macOS 启动与验收命令。

## 2. 已核对的差异

| 位置 | 当前实现 | 后续需要解决的问题 |
|---|---|---|
| API 类型和请求 | 已补齐 `Task.agent`、Artifact 展示字段和 `Citation.agent_source_id`；`api` 仍未提供原生结果查询方法 | 后续接入原生结果及用量 |
| 任务阶段与事件 | 阶段标签缺少 `agent_packaging`、`agent_waiting`、`partial`；英文未知事件可能退化为“任务已结束” | 补齐中英文显示和准确的未知阶段兜底 |
| 论文可选规则 | `canSelectPaper` 接受 `uploaded/ready`、拒绝 `processing`；Agent 后端接受 `uploaded/processing/ready` | 由服务端能力明确当前模式下的选择规则，不能全局放宽旧模式 |
| 研究输入参数 | 页面不提供手动预算，Agent 的旧 `budget` 仅含兼容值 | 后续技术信息区如展示限制须读取真实 `agent.limits`，不误报累计 Token 硬预算 |
| 比较表 | 已兼容旧结构化 `comparison_table` 和映射后的 Agent Markdown 表格 | 后续统一投影可进一步分离正文与比较内容 |
| 部分结果 | 已消费 Agent 的 `stop_reason/unresolved`，详情和历史显示“部分完成” | 保留旧任务 `retrieval` 提示，后续完善原生失败结果展示 |
| 失败结果 | `useTask` 只在成功时取产物，详情页失败时显示无结果；后端失败任务可能已保存原生结果 | 有结果可读，无结果才显示空态 |
| PDF 跳转 | `EvidencePanel` 输入论文及两类比较表引用已使用页内阅读，支持返回原任务/标签/引用 | 后续原生失败结果须沿用安全导航协议 |
| 返回定位 | 阅读返回参数要求合法 `artifactId`，而失败原生结果不生成 Artifact | 为无 Artifact 的结果定义稳定返回定位，不能伪造 Artifact ID |
| 任务标题和错误 | 标题、事件及错误可能来自后端中文文本，缺少 Agent 专用显示规则 | 补齐中英文界面文案，避免把原生停止原因裸露成产品说明 |

## 3. 固定边界

- 业务状态继续使用 `queued/running/succeeded/failed`。`partial` 是停止原因或阶段，不新增为业务状态。
- 后端负责用户归属、输入授权、动态限制和结果校验；Agent 负责研究。前端不补做检索、不调用模型，也不在失败后回退旧研究流程。
- 不让用户选择预算或传输方式；只提供必要的只读说明。
- 保留旧 `mock/langgraph` 任务和已有 Artifact 的展示能力，以每个任务冻结的信息判断，不能用当前服务模式解释历史任务。
- 保留当前布局、证据栏宽度、页内 PDF 高度、中英文切换、论文勾选恢复和移动端证据抽屉；本阶段不是重新设计页面。
- 平台内部 Slurm 状态不直接扩展成前端业务状态。现有接口未提供平台排队实时细节时，只能显示“等待 Agent 结果”，不能声称模型正在生成。

## 4. 接口现状与后端依赖

### 4.1 已有接口，前端可直接补齐接入

| 接口 | 已有字段或语义 | 前端用途 |
|---|---|---|
| `GET /api/v1/tasks/{id}` | 可空 `agent`，含 `dispatch_id/transport/remote_job_id/stop_reason/unresolved/limits` | 判断当前任务类型，显示执行信息、停止原因及只读限制 |
| `GET /api/v1/tasks/{id}/events` | 持久化有序事件，保持 `after_seq` 查询 | 执行记录、阶段、警告与错误 |
| `GET /api/v1/tasks/{id}/artifacts` | 成功任务的兼容展示；新增 `comparison_markdown/agent_stop_reason/unresolved`，引用含 `agent_source_id` | 成功结果和旧任务；失败任务当前返回空列表 |
| `GET /api/v1/tasks/{id}/agent-result` | 原生 `result`，未交付时为 `null`；失败任务也能返回已保存结果 | 停止原因、用量与失败研究内容；非 Agent 任务返回 404 |

原生结果的 `answer/comparison_table/citations` 使用 Agent 标识；后端兼容正文和 `comparison_markdown` 已按已保存的同一组引用转换为 `C1/C2`，浏览器夹具覆盖比较表引用、对应 PDF 页和返回定位。**不能把未经映射的原生 Markdown、现有 `C1` 点击插件和原生引用列表直接拼在一起。** `/agent-result` 中的原生内容仍保持不变。

### 4.2 尚未实现，需要后端配合的两项接口工作

以下为后续建议，不是当前可调用的接口承诺；统一修改时同步更新 API 契约和测试。

1. **研究能力查询。** 建议新增登录后可调用的 `GET /api/v1/research-capabilities`，返回当前创建任务所用 Runner、允许的论文状态、最大选中数以及自动限制模式。仅返回页面需要的非敏感能力，不返回 SSH、路径或模型密钥。名称和最终字段在实施时冻结。能力查询失败应显示重试，不能猜测后端模式；后端仍在创建任务时做最终校验。
2. **统一展示投影。** 建议扩展现有 `/agent-result` 响应，保留原生 `result` 不变，另外提供可空 `presentation`，包含分离的正文、比较表和稳定 `C1` 引用。复用后端同一套映射和授权校验，为成功与“失败但有原生结果”统一提供展示。投影按读取生成即可，不为失败任务伪造成功 Artifact，也不改变任务状态。

建议的投影至少包括 `content_markdown`（仅正文）、`comparison_markdown`（仅比较表）、映射后的引用、`stop_reason/unresolved` 及稳定 `result_key`；这些字段目前尚未存在。`result_key` 可绑定任务的 dispatch，不要求是 Artifact UUID。成功任务已有 Artifact 时沿用其身份；无 Artifact 的返回定位使用显式结果类型和 `result_key`，见第 5.5 节。

同一任务的展示来源按以下优先级选择，正文、比较表和引用必须来自同一来源，不能交叉拼装：

1. Agent `presentation` 非空且身份有效时，整组使用投影；已有 Artifact 只用于兼容既有返回身份，不再叠加其合并正文。
2. `presentation=null` 或新投影能力尚未部署时，成功任务可以整组回退到该任务的兼容 Artifact。旧结构化比较表保持原逻辑；Agent 兼容正文已经合并比较表，正文视图完整展示，比较标签使用已映射的 `comparison_markdown` 和同组引用，不猜测拆分正文。
3. 失败任务有原生 `result` 但没有投影时，显示停止原因、未解决项及“展示数据尚未就绪”的可重试提示；不把原生引用伪装为可点击的已映射证据。统一修改完成后，后端须为此类有效交付补齐投影，才能通过失败结果展示验收。

请求异常不是 `presentation=null`：保留已读取的同任务内容并显示重试；没有投影缓存的成功任务可使用兼容 Artifact，但保留原生查询异常说明。发生任务/输入身份冲突时拒绝该响应，不能用静默回退掩盖冲突。

在上述投影尚未实现时，可以完成已成功任务的兼容展示；不能将失败任务的原生引用直接当作已经映射、可点击的页面引用交付。

## 5. 前端待实施项

### 5.1 API 类型与统一结果模型（P0）

涉及：`frontend/src/api/types.ts`、`frontend/src/api/client.ts`，以及拟新增的研究结果适配模块。

- 已补齐可空 `Task.agent`、Agent 停止原因、Artifact 的 `comparison_markdown/agent_stop_reason/unresolved` 和 Citation 的 `agent_source_id`；原生结果响应及用量类型待后续接入。
- `Citation.chunk_id` 是不透明字符串，不能要求 UUID；`paper_id` 仍使用后端映射出的本地论文 ID。
- 新增带 AbortSignal 的原生结果查询；保持现有会话、错误和取消处理方式。
- 用统一的结果视图模型处理兼容 Artifact 和新的展示投影，避免三类任务页面各写一套转换。
- 为旧响应缺少字段、`agent=null`、`result=null`、用量未知及未知停止原因提供明确兜底。不能把所有 404 都解释为旧任务：已知 Agent 任务原生结果查询 404 应显示可重试错误。

### 5.2 论文选择和创建研究（P0）

涉及：`features/papers/lib/selection.ts`、`PaperPicker.tsx`、`PaperReadingList.tsx`、`pages/PapersPage.tsx`、`features/research/pages/NewTaskPage.tsx`；以上路径均位于 `frontend/src/`。

- 从同一能力来源向各选择入口传递规则，避免一个页面可选、另一个页面又禁用。Agent 模式允许 `uploaded/processing/ready`，`failed` 不允许；其他模式按服务端返回规则处理。
- Agent 模式的“解析中”表示旧解析器在更新元数据，不能因此禁止使用已上传原始 PDF；文案说明 Agent 会独立读取原文件。不要停止论文状态轮询或移除旧解析能力。
- 保持论文选择上限、三类任务篇数约束、幂等提交及“重新创建任务”的输入恢复。
- 能力尚未加载或不可用时显示加载/重试，避免先按错误规则启用提交；配置在提交前变化时正确展示后端拒绝结果。
- 保持创建请求不发送手动预算。

### 5.3 任务详情、阶段与结果获取（P0）

涉及：`features/research/hooks/useTask.ts`、`pages/TaskDetailPage.tsx`、`pages/TasksPage.tsx` 和 `shared/lib/format.ts`，均位于 `frontend/src/`。

- 补齐打包、等待 Agent 结果及部分完成的阶段名称；列表保留简单状态，详情展示原因和警告。
- 先读取任务以判断是否 Agent，再查询原生结果；成功任务可同时保留兼容 Artifact。失败也要查询已保存原生结果，不因业务状态失败而隐藏内容。
- 原生结果查询失败与“接口成功返回 result=null”是不同情况；前者显示错误及重试，后者按任务状态显示等待或无结果空态。
- 保留事件增量去重、终态事件补齐、卸载取消请求及手动刷新；切换 taskId 时同步清理结果、错误和引用选中状态，防止短暂显示上一任务内容。
- 平台等待不显示虚构百分比，不新增实时 Token 流或伪造 Agent 工具执行事件。
- 无原生结果的包装器/平台失败只显示安全错误及输入；有原生结果的失败显示失败说明和“已保留的研究内容”，不标记为成功。

### 5.4 正文、比较表与证据不足提示（P0）

涉及：`ArtifactView.tsx`、`ComparisonView.tsx`、`EvidenceCoverageNotice.tsx`、`EvidencePanel.tsx`、`lib/citationLinks.ts` 及详情页，位于 `frontend/src/features/research/`。

- 比较标签支持两类来源：旧结构化 `comparison_table` 和 Agent 映射后的 Markdown 比较表；没有比较内容则隐藏标签。
- 以统一投影分离正文和比较表，明确“研究结果/综述正文”和“论文比较”的内容边界；不能通过猜测 Markdown 标题或字符串截断拆分旧兼容正文。
- Agent 比较表复用 Markdown 安全渲染和引用按钮，保持禁用原始 HTML、图片及危险链接协议；不强行解析成旧结构化表格。
- `partial` 和非空 `unresolved` 显示具体未解决项；旧 `retrieval` 提示只适用于旧任务。避免同时出现两套重复或相互矛盾的证据不足提示。
- 有正文无引用、有表无正文、空比较表、长表和小屏幕均有明确显示规则；未知引用保留可读文字，不伪造成可点击来源。
- 任务标题优先使用三类任务的产品名称及中英文映射，不直接依赖后端固定中文标题。

### 5.5 引用、PDF 阅读与返回定位（P0）

涉及：`EvidencePanel.tsx`、`ArtifactView.tsx`、`shared/lib/paperReader.ts`、`features/papers/pages/PapersPage.tsx` 和 `components/PaperReader.tsx`，均位于 `frontend/src/` 相应目录。当前详情页没有独立 `TaskInputs` 组件。

- 研究输入论文链接、正文和比较表引用已使用页内阅读路由；继续统一使用后端映射的本地 `paper_id` 与 PDF 物理 `page_number`，后续原生失败结果也须遵守。
- 不从原生 `url`、标题或字符串形式的 source_id 猜测本地论文 ID；不把远程文件系统路径作为浏览器 PDF 地址。
- 保留“返回任务”按钮和任务/结果/正文或比较视图/当前引用定位。成功 Artifact 沿用已有 URL 参数；失败原生结果采用独立定位形式。
- 建议扩展阅读返回协议，显式标记 `artifact/agent` 结果类型；Agent 结果携带 `taskId + result_key`，不制造假的 Artifact UUID。旧 `return_artifact` 链接继续兼容，参数校验和返回路径仍限制在站内。
- 返回新建研究时继续恢复已勾选论文。新建研究、输入论文列表及没有当前引用的页面，也应能返回原位置，不要求必须存在 Artifact 或 citationKey。
- 刷新阅读页、重新加载任务以及切换语言后，引用键和定位保持稳定；不存在的引用有安全兜底。页码未知/越界、PDF 不可用和访问失效时显示可恢复提示，不伪造有效来源。

### 5.6 执行限制、统计与技术信息（P0/P1）

涉及：任务详情后续技术信息区、运行统计区和 API 类型。

- Agent 模式读取 `task.agent.limits`，展示“系统自动分配”的 Agent 主循环步数、每次模型输出上限及总超时；有对应字段时可展示上下文窗口。具体字段以服务端契约为准。
- 不把旧兼容 `budget.max_tokens` 显示为 Agent 累计 Token 硬预算，不把 Agent 主循环步数说成模型调用次数，不把每次输出上限说成整份综述总长度。
- 输入/输出/总 Token、模型/工具调用展示实际报告值；`null` 显示“未报告”，0 仍是 0。用量不完整时说明统计不完整，不能推算为完整计费值。
- 区分后台任务耗时与 Agent 自报耗时，平台等待包含在任务总时限内，不能将全部 running 时间标成模型生成耗时。
- P1：将 dispatch ID、remote job ID、传输类型和安全错误码放入可折叠“任务信息”，支持复制以便排查。面向普通用户仍使用简洁阶段说明。
- P1：如需展示原生 trace/errors/configuration，先由后端定义脱敏白名单，仅展示操作、耗时和安全错误摘要，不把任意原生字典直接渲染成调试面板。首批适配不依赖此能力。

### 5.7 国际化与错误说明（P0）

涉及：`frontend/src/i18n/messages.ts`、`diagnostics.ts`、`shared/lib/format.ts` 和相关组件。

- 补齐 Agent 阶段、原生停止原因、未解决项、无结果、查询失败、限制和运行信息的中英文文案。
- 为已实现的 `AGENT_*` 平台/进程/包装器/投递错误和原生停止原因映射用户说明，范围以 [对接说明](agent-backend-integration.md) 及后端实际错误码为准。
- 覆盖 `completed/partial/step_limit/time_limit/context_limit/model_error/invalid_tool_call/output_truncated/invalid_output/invalid_citations/insufficient_evidence`。未知值保留安全代码并显示通用提示，不误报任务完成。
- 已知错误按代码或结构化 payload 翻译；未知进度只作中性状态提示。不要将后端新中文事件在英文模式下一律翻成“任务执行已结束”。
- 区分界面语言与研究输出语言：切换 UI 只翻译产品文案，不自动翻译已经生成的正文、引用原文、用户问题和未解决项文本。若以后需要指定输出语言，应另行约定任务字段和 Agent 行为，本次不作隐式承诺。

## 6. 结果状态显示矩阵

| 业务状态 | Agent 结果 | 页面行为 |
|---|---|---|
| queued | null | 等待领取，可离开页面后恢复查询 |
| running | null | 当前已知阶段、执行记录、等待完整结果；不展示伪造研究正文 |
| succeeded | completed，且无 unresolved | 正常正文、可选比较表、证据及用量 |
| succeeded | partial 或含 unresolved | 正常显示可用内容，同时突出具体未解决项；不改业务状态 |
| failed | 有已保存原生结果 | 保留失败说明，展示已返回内容和已验证引用；结果为空文本时显示停止原因与未解决项，不伪造正文 |
| failed | null | 显示失败原因、研究输入及重新创建入口；无结果不显示假引用 |
| 任意 | 原生结果请求失败 | 显示可重试查询错误，不能断言无结果，也不覆盖已读取内容 |

后端只以完整、校验通过的交付结果生成投影。包装器/进程失败没有完整研究结果时不生成假投影；原生结果存在也不意味着其中每个结论已经被人工核实。

## 7. 建议实施顺序与改动组织

| 顺序 | 工作包 | 前置条件与产出 |
|---|---|---|
| 4.1 | 冻结能力查询、展示投影和阅读返回契约；补齐类型及请求 | 先确认第 4.2 节两个后端依赖，新增契约夹具与映射测试 |
| 4.2 | 论文选择、任务阶段、原生结果获取及限制文案 | 从任务冻结信息识别历史 Agent 任务，三类任务共用结果模型 |
| 4.3 | Markdown 比较表、证据提示、失败结果和 PDF 返回 | 引用映射和无 Artifact 返回定位先通过夹具测试 |
| 4.4 | 国际化、浏览器回归、完整验收及文档更新 | 覆盖两种语言、三类任务、旧任务、本地/TACC 和异常场景 |

优先级说明：P0 为统一修改必须完成的适配；P1 为便利性增强，可在完成 P0 后同批补充。原生 trace 调试面板、模型实时流式输出、平台实时排队进度不作为本次完成条件。

不建议将全部逻辑堆入 `TaskDetailPage.tsx`。可在现有 research feature 下新增结果视图模型、Agent 状态提示及 Markdown 比较组件，沿用现有 API 层、国际化层和阅读路由。具体文件名在实施时确定，不另建平行页面或第二套引用体系。

## 8. 统一验收清单

以下均为待执行项；本文不表示测试已新增或验收已完成。

- [ ] 能力查询加载、成功、失败与重试正确；Agent 和旧模式论文状态规则一致贯穿所有选择入口。
- [ ] 已上传、解析中、就绪、失败四种论文状态分别测试；旧模式原有规则没有被全局放宽。
- [ ] 摘要、问答、综述均可创建，论文数量规则与幂等提交不回退，页面没有预算输入。
- [ ] 已知阶段、未知阶段、超时和安全错误在中英文下准确；等待过程不误报“已结束”。
- [ ] completed、partial、unresolved、失败有结果、失败无结果均按第 6 节展示。
- [ ] 原生结果的 null、查询失败、404 和历史非 Agent 任务分开处理，不因接口失败丢失已读取结果。
- [ ] Agent Markdown 比较表和旧结构化比较表分别可读；无表不显示空比较标签，正文不靠字符串猜测拆分。
- [ ] 投影与 Artifact 同时存在、投影为空、投影查询失败和身份冲突均按第 4.2 节处理，不重复正文/比较表，不交叉混用引用。
- [ ] 正文/比较表中的引用可点击；多引用、未知引用、无引用和超过 C9 的引用均无错配。
- [ ] 引用跳转到对应原始 PDF 物理页，覆盖中间空白页；跨任务、跨论文和不可用 PDF 不产生错误链接。
- [ ] 输入论文点击也使用页内阅读；返回按钮恢复任务、正文/比较视图及当前引用。
- [ ] 无 Artifact 的失败结果同样可往返；旧阅读 URL 和新建研究勾选状态保持兼容。
- [ ] 页面刷新、快速切换任务及网络恢复不会显示其他任务的正文或引用，也不会重新提交研究。
- [ ] 限制标签区分主循环步数、单次输出上限和任务超时；不出现虚构的 Agent 累计 Token 硬预算。
- [ ] 用量未知、0、不完整以及长正文/长表在中英文和移动端均正确显示。
- [ ] 历史 mock/langgraph 结果、模拟标记、阅读抽屉、布局和语言切换保持可用。
- [ ] 本地模式及 TACC 模式分别完成一次真实上传到结果与引用阅读的闭环；刷新/重启不增加研究执行。

### 开发检查命令

以下 Windows PowerShell 和 macOS 终端均从项目根目录执行，前提是已安装项目依赖；只在后续实际修改后运行，不表示本轮已执行。

```text
npm --prefix frontend run typecheck
npm --prefix frontend run verify:review
npm --prefix frontend run build
```

现有 `frontend/checks/review.mjs` 主要覆盖自动预算、幂等摘要及部分双语行为，不能替代全部 Agent 验收。需扩展其适用检查，并参考 `review-browser.py`、`evidence-reader-browser.py`、`library-reader-browser.py` 补充 Agent 夹具。浏览器测试应模拟能力、任务、事件、原生投影、旧产物及文件接口，不发真实模型或 arXiv 请求；真实部署闭环另行记录。

检查记录应区分：离线自动检查通过、浏览器夹具通过、真实 local 验收、真实 TACC 验收。后续有后端契约修改时，同时执行对应后端测试，不将前端构建通过视为端到端通过。

## 9. 本阶段不包含的事项

- 不重新美化 AuthGate、论文搜索或全站布局；与 Agent 无关的页面保持现状。
- 不新增用户手动预算、用户选择 Runner、用户选择传输方式或复杂平台状态。
- 不实现新的任务取消按钮、自动重跑、Agent 流式 Token 或完整工具事件流；这些需单独约定后端契约。
- 不直接删除旧 Parser 和旧 Runner，不更改已有数据归属或清空历史任务。
- 不把 SSH、Slurm、模型部署及账号权限配置交给浏览器。

统一修改完成后，更新本文勾选项、[API 契约](api-contract.md) 和 [对接说明](agent-backend-integration.md)，记录实际测试、真实环境验收结果及仍未完成项。
