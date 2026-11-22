# Agent workflow

本文区分当前 baseline 与后续 extensions；功能效果随评测验证。模块关系沿用下图，箭头表示数据流与调用反馈，执行顺序由 agent 根据任务和观察决定。

![Baseline 与 extensions](./workflow.png)

## 任务与接口

| 任务 | 主要输出 | 关注点 |
|---|---|---|
| 论文总结 | 研究问题、方法、结果、实验条件与局限的总结 | 覆盖主要章节，保留结论适用条件 |
| 论文 QA | 带引用的回答、依据与无法判断之处 | 对齐问题与原文，区分报告事实和推断 |
| 课题综述与比较 | 限定范围的综述及关联支持段落的比较表 | 跨论文综合、字段覆盖、实验条件可比性 |

当前输入包含 `task_id`、`question`、来源列表、是否允许搜索、篇数上限，以及 `max_steps`、`timeout_seconds`、`max_output_tokens`。来源可以是 arXiv ID/URL 或库内 `local:<UUID>@<sha256>` 标识。`question` 直接表达问答、总结、比较或混合要求，由 agent 据此选择工具和组织回答。任务与结果类型见 [schemas.py](schemas.py)。任意本地文件、更多资料过滤条件和 `baseline / extended` 切换留待扩展接入。

输出包含正文、比较表（适用时）、引用与证据定位、未解决项、停止原因和运行统计。表格按字段关联证据，区分未报告、不适用、证据不足和冲突。

## Baseline

主图由 agent 和 tools 两个节点组成。`@tool` 定义的工具按模型请求顺序串行执行，模型提交最终 JSON 时结束。

Agent 使用任务提供的论文。需要补充论文且允许搜索时，可用搜索工具寻找候选。可先用 `open_paper` 查看目录与页数，再按需要用摘要粗读页段或用 `read_paper` 精读原文。Extension 还可用 `retrieve` 在选定论文中定位相关段落。工具返回 `already_read` 或 `already_summarized` 时，复用对应页段的已有结果。

| 工具或处理 | 行为 |
|---|---|
| `search_papers` | 搜索 arXiv 候选；搜索片段只用于发现，不作引用证据 |
| `search_library` | 按标题或文件名搜索当前用户的论文库，返回候选的 `source` |
| `open_paper` | 下载、解析并缓存论文，返回标题、版本、总页数及 PDF 书签目录 |
| `read_paper` | 读取允许论文的 1–3 页原文块，返回页码、chunk ID 和总页数 |
| `summarize_paper` | 将最多 6 页分批交给模型摘要，摘要引用关联原文块 |

打开、阅读与摘要复用本次运行中已解析的论文。打开论文只返回导航信息，原文证据在读取或成功摘要后登记。arXiv PDF 缓存在本地，库内 PDF 通过当前用户的令牌下载到临时目录。启用持久化时，解析后的论文及结果保存到数据库。原文与摘要分别去重，摘要后可再读取原文核实。

主模型调用前按 `context_policy` 准备输入视图。两版默认使用 `full`，可切换为 `compact`。估算输入加本次输出额度达到窗口的 `context_finalize_ratio`（默认 `0.9`）时，`compact` 先用程序精简工具回包。准备后仍达到阈值即进入一次无工具收尾。超窗时按无工具请求重估，必要时保留任务和可容纳的证据，再检查最终请求容量。保存的历史、原文证据和工具记录保留。分块摘要独立准备完整输入。

## Extensions

Extension 复用 ReAct 图、论文工具与 context 策略，新增 `retrieve`。该工具在指定的一篇或多篇论文中联合检索。首次检索时复用已打开论文的解析结果，逐篇按需为原文块建索引并缓存在本地。每次调用生成一个查询向量，在全部选中论文中按余弦相似度取全局前 `top_k` 个块，仅登记实际返回的原文块为检索证据。[实验结果](../RESULTS.md) · [后续计划](../PLAN.md)

| 模块 | 职责与返回内容 |
|---|---|
| Planner（`--planner` 开启） | 起始无工具调用，返回空计划或 1–3 行建议，写入 `state.plan` 供主 agent 参考 |
| Chunk & Embed | 将获取的正文分块、生成向量，保留原文和来源定位 |
| Vector DB | 存储文本块、向量及来源信息，供已获取材料的重复检索 |
| Retrieval | 在允许的文献范围内按子问题检索，返回相关原文、定位及必要的相邻上下文 |
| Reflection（`--reflection` 开启） | 在自然交稿后对照正文、表格与引用原文，接受草稿、直接修订或补证一次后无工具修订 |

存储与读取路径为 **Chunk & Embed → Vector DB → Retrieval**。Paper DB 管文献，Vector DB 管可检索文本块；embedding 后仍由 LLM 阅读证据、综合作答。检索后的问题定向摘要可按上下文需要加入。

Planner 与 Reflection 可独立开启，默认均关闭。Planner 的非空建议附在初始任务消息的原任务 JSON 之后。Reflection 只接收主 agent 自然提交且可解析的草稿，需要更多原文时可选一次 `read_paper` 或 `retrieve`。接受或修订后的答案统一进入最终校验。压力收尾直接进入最终校验。

DeepSeek Harness 的待办工具让模型在简单单步任务上跳过清单，Pi 的 Plan Mode 示例通过开关显式启用。本项目让 Planner 自行判断是否有容易遗漏的证据要求。即使是多篇比较，如果原任务已经足够明确，也可以返回空计划。[DeepSeek Harness 待办工具](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/todo/tool-todo/src/index.ts) · [Pi Plan Mode 示例](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/plan-mode/index.ts)

## 证据与状态

证据记录至少包含 `source_id`、`paper_id`（适用时）、版本、`chunk_id`、章节或页码及 `source_text`。摘要、答案论断和比较表单元格关联这些记录；可用的定位精度由解析结果决定。

当前 `GraphState` 保存消息、停止原因和最终输出，Extension 另存本次计划。资料、证据及运行记录由单次运行维护。

| 状态项 | 内容 |
|---|---|
| Task | 原问题、输出要求、允许来源、主 agent 轮数和时间上限 |
| Sources | 候选与纳入文献、版本、全文状态、去重和筛选记录 |
| Evidence | 原文块、摘要、来源定位、论断或比较字段的证据关联 |
| Progress | 计划、工具历史、候选输出、未解决项 |
| Usage | 时间、API 返回的 token、主 agent 轮数、模型/工具调用数与错误 |

整任务限制为最大主 agent 轮数与时间，默认分别为 40 轮和 600 秒；自然最终回答和压力收尾都占一轮，摘要调用另计入模型用量。到限直接停止并保存 `stop_reason`、证据和 trace；不因最后一轮、剩余时间或无进展提前收尾。时间在调用前后检查，并限制单次请求超时。

运行参数 `context_window` 默认 `32000`，不是任务字段；最终待发请求的估算输入加本次输出额度超过窗口时，记录 `kind="context"` 并停止为 `context_limit`，不增加实际模型调用数或主 agent 轮数。Python 传 `context_window=None` 关闭本地上限及压力收尾；仅禁用收尾可传 `context_finalize_ratio=None`。服务端容量错误仍记录 `context_limit`。本地计数先按字符、消息包装和工具定义估算，后续在历史前缀及工具定义匹配时，以 API 输入用量校准并估算新增内容；主 agent 与摘要分别计数。该估算不等于服务端 tokenizer，不补入 API usage。

收尾触发记录为 `kind="context", action="finalize", reason="context_pressure"`，实际模型调用为 `purpose="finalize"` 并计入主 agent 轮数和模型成本。触发原因与最终结果分开：收尾回答仍经原有解析、引用与未解决项检查，可能为 `completed`、`partial` 或错误状态。

## 实现顺序

1. 固定输入、输出和证据结构，接通模型客户端，用单篇 QA 跑通 ReAct 调用、补读、引用和停止。
2. 接入 Source Search 与长文分块摘要，覆盖论文总结、综述和比较表；保留可复现的 baseline 配置与 trace。
3. 验证 context 压力收尾，先在独立的 Extension 入口接入按需建索引与 Retrieval，沿用 Baseline 的执行与收尾。
4. 在 Extension 对照完整历史与程序压缩，再分别试验 Planner、Reflection。
5. 用相同任务与允许资料检查遗漏、无证据回答、不同实验条件和全文不可得等情况，记录策略与成本差异，按结果调整实现。

Baseline 使用 LangGraph、搜索 API、PDF parser 和 PostgreSQL。首版 Extension 使用百炼 embedding 与本地向量索引，后续再评估 pgvector。

## 评测接口与相关文档

两版共享任务与结果格式。Trace 记录工具参数及来源、证据、候选输出、检查反馈、耗时和消耗，支持回放与失败分析。控制、摘要、规划、反思和修订调用均计入模型成本；embedding 与建库另计，并标明是否复用索引。

整体任务、对照设置和评分见 [项目方案](../docs/design.md)；模块对接约定维护在 [interfaces](interfaces.md)，平台入口见 [TACC](../tacc/README.md)。主流程通过模型客户端调用 TACC 服务。

设计主要借鉴 [PaperQA2](https://arxiv.org/html/2409.13740v2) 的动态调查：搜索文献、收集证据、尝试回答，再决定继续或结束。这里的 extensions 相对于本项目 baseline。
