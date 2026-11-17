# Agent Baseline 输入输出接口 v1

更新：2026-11-17。依据当前 `agent/schemas.py`、`agent/baseline.py`、`agent/context.py` 和 `agent/apis/papers.py` 整理。

本文约定 Agent 的任务输入与结果输出。当前提供 Python 函数和本地 CLI，跨模块调用、传输及部署方式尚未联调；本文不定义 HTTP 路由。

Agent 支持可选的 Neon 持久化：`persist=false`（默认）不写入数据库；`persist=true` 保存论文和运行结果。`persist`、`context_window` 和 `context_policy` 属于运行参数，不放在任务输入 JSON 中，调用方式见第 4 节。

## 1. 输入

完整输入示例：

```json
{
  "task_id": "task-001",
  "question": "为什么 attention 要除以 sqrt(d_k)？",
  "sources": ["1706.03762v7"],
  "allow_search": false,
  "max_papers": 3,
  "max_steps": 40,
  "timeout_seconds": 600,
  "max_output_tokens": 4096
}
```

| 字段 | 类型 | 必填 | 说明 / 默认值 |
|---|---|---|---|
| `task_id` | string | 否 | 默认自动生成 UUID 十六进制字符串；后端可传入自己的任务 ID |
| `question` | string | 是 | 用户问题或任务要求，可表达问答、总结、比较或混合要求；长度至少为 1，当前不自动去除首尾空白 |
| `sources` | string[] | 条件必填 | arXiv ID 或 URL；默认 `[]` |
| `allow_search` | boolean | 否 | 是否允许搜索补充论文；默认 `false` |
| `max_papers` | integer | 否 | 最多获取的不同论文数量，范围 1–20；默认 3 |
| `max_steps` | integer | 否 | 主 agent 最多调用轮数，至少为 1；默认 40 |
| `timeout_seconds` | number / null | 否 | 整任务时间上限，单位秒；非空时须大于 0；默认 600，`null` 禁用整任务时间上限 |
| `max_output_tokens` | integer | 否 | 单次主模型输出 token 上限，至少为 1；默认 4096 |

输入约束：

- `allow_search=false` 时，`sources` 必须非空；设为 `true` 时可以不提供论文。
- 当前来源支持 arXiv ID、带版本 ID，以及 arXiv 的 abs/pdf/html URL；暂不支持本地 PDF 路径或任意网站 URL。
- `task_id` 长度 1–101，首字符为英文字母或数字，其余允许英文字母、数字、`.`、`_`、`-`。
- 任务对象不接受未定义字段。旧版 `budget`、`task_type` 已移除，传入会抛出校验错误。
- `max_papers` 限制实际获取的不同论文数量，不限制输入列表长度或搜索候选数量。

执行参数含义：

- `max_steps` 包含最终回答所在轮；摘要工具内部的模型调用不占主 agent 轮数，但计入 `usage.model_calls`。一轮可请求多个工具，当前按返回顺序串行执行。
- 达到轮数或时间上限直接停止，不追加最终回答调用。最后一轮若仍请求工具，该轮工具不会执行。
- 时间限制通过调用前后检查及收紧单次请求超时实现，不是到点强杀。`timeout_seconds=null` 不取消各适配器的单次请求超时。
- 摘要内部每次模型调用的输出上限为 `min(1200, max_output_tokens)`。
- 当前不设置独立的工具调用次数上限或累计 token 预算。运行参数 `context_window` 默认 `32000`；主模型和摘要调用前，估算输入加本次输出额度超过窗口则停止为 `context_limit`，不发起该次模型调用。服务端可识别的容量错误也记录为 `context_limit`。
- 默认 `prepare_context` 保留完整历史，不自动压缩或追加收尾调用，也不根据连续无进展强制生成答案。它不额外调用模型；本地容量拦截不增加 `usage.model_calls` 或 `usage.agent_steps`。

最小输入：

```json
{
  "question": "总结这篇论文的方法和实验结果",
  "sources": ["1706.03762v7"]
}
```

任务意图统一由 `question` 表达，无需另行指定任务类别。Agent 根据其中的要求选择工具和组织回答；例如可写成“先总结方法，再比较实验条件并回答以下问题”。

## 2. 输出

返回 `TaskResult`，序列化后的主要字段如下。正文与统计值仅作示例；完整返回还包含 `trace` 和 `configuration`，在下文单独说明。数组可以为空，也可以包含一个或多个元素。

```json
{
  "task_id": "task-001",
  "question": "为什么 attention 要除以 sqrt(d_k)？",
  "answer": "回答正文…… [arxiv:1706.03762v7:p4:c1]",
  "comparison_table": "",
  "citations": [
    {
      "chunk_id": "arxiv:1706.03762v7:p4:c1",
      "source_id": "arxiv:1706.03762v7",
      "paper_id": "arxiv:1706.03762",
      "version": "v7",
      "page": 4,
      "source_text": "对应的论文原文片段……",
      "url": "https://arxiv.org/abs/1706.03762v7",
      "title": "Attention Is All You Need"
    }
  ],
  "unresolved": [],
  "stop_reason": "completed",
  "usage": {
    "agent_steps": 3,
    "model_calls": 3,
    "tool_calls": 2,
    "input_tokens": 7253,
    "output_tokens": 594,
    "total_tokens": 7847,
    "token_usage_complete": true,
    "elapsed_seconds": 17.947
  },
  "sources": [
    {
      "paper_id": "arxiv:1706.03762",
      "source_id": "arxiv:1706.03762v7",
      "title": "Attention Is All You Need",
      "url": "https://arxiv.org/abs/1706.03762v7",
      "version": "v7"
    }
  ],
  "errors": []
}
```

完整结果的顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 本次任务 ID |
| `question` | string | 原始问题或要求 |
| `answer` | string | Markdown 正文，可能为空字符串 |
| `comparison_table` | string | Markdown 表格；不适用时为 `""` |
| `citations` | object[] | 正文及表格实际引用、且本次已获取的原文证据 |
| `unresolved` | string[] | 未解决问题或停止、证据不足等说明 |
| `stop_reason` | string | 本次运行的最终停止原因，见第 3 节 |
| `usage` | object | 主 agent 轮数、调用次数、token 消耗与执行耗时 |
| `sources` | object[] | 实际获取的论文元数据，按 `source_id` 去重 |
| `trace` | object[] | 本次运行的模型、工具及本地上下文拦截记录 |
| `errors` | object[] | 错误摘要，每项包含 `stage` 和 `type` |
| `configuration` | object | 本次运行采用的完整任务、模型及上下文配置 |

引用与来源约定：

- 正文中的 `[arxiv:1706.03762v7:p4:c1]` 对应 `citations[].chunk_id`；比较表中的引用使用相同方式。
- `source_text` 是 PDF 解析出的原文片段，可供前端展开查看；通过摘要获得的证据也保留原文。
- `page` 是从 1 开始的 PDF 页序号，不一定等于论文印刷页码。
- `paper_id` 标识论文，`source_id` 标识所获取版本或内容，`chunk_id` 标识具体原文块。无法确定版本时，当前适配器可能返回 `version=null`，并以文件摘要构成 `source_id`，例如 `arxiv:1706.03762@012345abcdef`。调用方应原样保存、匹配这些 ID，不依赖固定的 `vN` 格式。
- `citations` 只包含最终正文和表格实际引用的有效证据，不是本次全部已读证据。`sources` 不是输入列表或搜索候选列表，也不代表每篇论文已被完整阅读。
- 引用校验确认 ID 存在且原文经过本次读取或成功摘要处理；不代表已自动验证语义支持程度或论文覆盖完整性。

统计约定：

| 字段 | 含义 |
|---|---|
| `agent_steps` | 主 agent 模型调用次数，包含生成最终回答的调用 |
| `model_calls` | 所有模型调用次数，包含主 agent 和工具内部摘要调用 |
| `tool_calls` | 实际开始处理的工具调用次数，包含参数错误等失败尝试 |
| `input_tokens` / `output_tokens` / `total_tokens` | 所有模型调用的累计 API token 统计，可为 `null` |
| `token_usage_complete` | 是否取得每次模型调用的完整 token 统计 |
| `elapsed_seconds` | Agent 执行耗时，单位秒；不含后端排队、随后的 Neon 保存和 CLI 结果文件写入 |

调用次数包含已发起的失败尝试，不包含调用前的本地容量拦截。任一次模型调用缺少完整 usage 或调用失败时，三个累计 token 字段均置为 `null`，同时 `token_usage_complete=false`；不使用估算值补齐。当前没有 `budget_tokens` 字段。

### 2.1 执行记录 `trace`

`trace` 是事件数组，各项结构由 `kind` 决定。下面展示“主模型请求阅读工具 → 工具返回结果”的两条记录；文本和部分消息元数据已简化，统计值仅作示例。

```json
{
  "trace": [
    {
      "kind": "model",
      "purpose": "agent",
      "output_limit": 4096,
      "context": {
        "window": 32000,
        "input_tokens_estimate": 1100,
        "count_method": "heuristic"
      },
      "messages": [
        {
          "type": "system",
          "content": "系统提示词……"
        },
        {
          "type": "human",
          "content": "{\"task_id\":\"task-001\",\"question\":\"为什么 attention 要除以 sqrt(d_k)？\",\"sources\":[\"1706.03762v7\"],\"allow_search\":false,\"max_papers\":3}"
        }
      ],
      "response": {
        "type": "ai",
        "content": "",
        "tool_calls": [
          {
            "id": "call_1",
            "name": "read_paper",
            "args": {
              "source": "1706.03762v7",
              "page_start": 4,
              "page_end": 4
            },
            "type": "tool_call"
          }
        ],
        "response_metadata": {
          "finish_reason": "tool_calls"
        },
        "usage_metadata": {
          "input_tokens": 1000,
          "output_tokens": 50,
          "total_tokens": 1050
        }
      },
      "elapsed_seconds": 2.35
    },
    {
      "kind": "tool",
      "name": "read_paper",
      "arguments": {
        "source": "1706.03762v7",
        "page_start": 4,
        "page_end": 4
      },
      "observation": {
        "source_id": "arxiv:1706.03762v7",
        "title": "Attention Is All You Need",
        "page_count": 15,
        "pages_read": [4],
        "chunks": [
          {
            "chunk_id": "arxiv:1706.03762v7:p4:c1",
            "source_id": "arxiv:1706.03762v7",
            "paper_id": "arxiv:1706.03762",
            "version": "v7",
            "page": 4,
            "source_text": "对应的论文原文片段……"
          }
        ],
        "previously_read_chunk_ids": [],
        "status": "complete"
      },
      "elapsed_seconds": 0.18
    }
  ]
}
```

模型记录：

- `purpose`：`agent` 表示主循环，包含最终回答调用；`chunk_summary` 表示工具内部的分块摘要调用。
- `messages` 和 `response` 是 LangChain 消息对象的序列化结果，不是供应商原始 HTTP 请求和响应。`messages` 记录准备后实际发送的输入视图；默认策略保留此前消息和工具结果，自定义主历史策略可返回不同视图。
- 初始 human message 包含任务 JSON：`task_id`、`question`、`sources`、`allow_search`、`max_papers`。`question` 原样传入主模型；程序不按任务类型分流。
- `max_steps`、`timeout_seconds`、`max_output_tokens` 不进入该任务消息；补齐默认值的完整任务保存在 `configuration.task`。
- 分块摘要调用的 human message 只包含原始 `question` 和本批 `chunks`。
- `output_limit` 是本次模型调用配置的最大输出 token 数；`response.usage_metadata` 是本次 API 返回的用量，可能缺失。
- `context` 包含运行窗口 `window`（可为 `null`）、本次估算输入 `input_tokens_estimate` 和计数方式 `count_method`。默认方式为 `heuristic` 或 `usage_anchored_estimate`，均不是精确 tokenizer 计数。
- 模型调用失败时，保留 `kind`、`purpose`、`output_limit`、`context`、`messages` 和 `elapsed_seconds`，以 `error` 记录异常类型，不包含 `response`。

默认计数先按序列化请求中的 ASCII 字符数 / 3、非 ASCII 字符数 × 2，加消息包装与工具定义估算。已有 API `input_tokens` 且历史前缀、工具定义均匹配时，改用该输入用量加新增消息估算；否则回退为 `heuristic`。主 agent 与摘要分别维护计数锚点。估算仅用于本地容量检查，不替代 API usage；实际 TACC 窗口和 tokenizer 仍待对齐。

本地容量拦截记录使用 `kind="context"`，包含 `purpose`、`context`、`output_limit`、`stop_reason="context_limit"` 和准备后的 `messages`；没有 `response` 或模型调用耗时。它表示请求尚未发出，与 API 返回上下文超限时的失败 `kind="model"` 记录不同。

工具记录：

- `name`、`arguments` 是模型请求的工具名称和参数；`observation` 是工具结果，结构随工具而变化。
- 失败时，`observation` 包含 `error` 和 `type`。运行上下文由程序注入，不属于模型工具参数。
- 工具记录不含模型容量估算；各类记录均不维护累计剩余 token 预算。

当前工具的记录概要：

| 工具 | 模型输入 | 成功时的 `observation` |
|---|---|---|
| `search_papers` | `query` | `results`（每项含 `source/title/url/snippet`）、`evidence_status="discovery_only"`；仅允许搜索时提供 |
| `open_paper` | `source` | `source_id/title/version/page_count/outline`；`outline` 为 PDF 书签目录，每项含 `title/level/page_start`，无目录时为 `[]` |
| `read_paper` | `source/page_start/page_end`；1–3 页 | `source_id/title/page_count/pages_read/chunks/previously_read_chunk_ids/status`；状态为 `complete` 或 `already_read` |
| `summarize_paper` | `source/page_start/page_end`；1–6 页 | `source_id/title/page_count/pages_summarized/summaries/previously_summarized_chunk_ids/status`；每项摘要含 `summary/chunk_ids`，状态为 `complete` 或 `already_summarized` |

搜索片段只用于发现论文，不能直接作为引用证据。打开论文返回导航信息，不登记引用证据；打开、阅读与摘要共用论文缓存。阅读和摘要分别去重；摘要后仍可读取原文。工具的 `complete` 表示本次返回了新块或摘要，不表示整篇论文已读完。

记录不一定按 model/tool 两条交替：一次摘要工具内部的 `chunk_summary` 模型记录会先追加，再追加外层 `summarize_paper` 工具记录。工具耗时包含其内部模型调用，不能把所有 trace 耗时相加当作任务总耗时。

后端可将 `trace` 整体作为 JSON 保存；当前随最终结果一次返回，不提供进度事件流。当前不产生 `purpose="final"`、上下文压缩或 `no_progress` 控制记录。

### 2.2 运行配置 `configuration`

| 字段 | 说明 |
|---|---|
| `task` | 补齐默认值后的完整输入任务，包含第 1 节的三个执行参数 |
| `model` | 实际使用的模型标识；未取得时为 `null` |
| `temperature` | 实际使用的温度参数；未取得时为 `null` |
| `context_window` | 本地估算输入加输出上限，默认 `32000`；`null` 表示关闭本地上限 |
| `context_policy` | 主 agent 使用的策略函数名，默认 `"prepare_context"`；可调用对象无函数名时记录类名 |

当前结果构造始终包含这五个键。`context_window/context_policy` 不属于 `configuration.task`；`persist` 不记录在 `configuration` 中。

## 3. 结果状态与错误处理

| `stop_reason` | 含义 |
|---|---|
| `completed` | 最终输出已解析，至少引用一条有效原文证据，无未知引用，且 `unresolved` 为空 |
| `partial` | 最终输出已解析且引用检查通过，但存在 `unresolved` |
| `step_limit` | 达到主 agent 轮数上限，未生成最终回答 |
| `time_limit` | 检查时已达到整任务时间上限 |
| `context_limit` | 本地估算输入加本次输出额度超过窗口，或模型 API 返回可识别的 `context_length_exceeded` 错误 |
| `model_error` | 模型初始化、工具绑定或模型调用失败；未识别为上下文超限的模型错误也归入此项 |
| `invalid_tool_call` | 主模型响应包含无法正确解析的工具调用 |
| `output_truncated` | 主模型响应的 `finish_reason="length"`，输出被截断 |
| `invalid_output` | 最终回答无法解析为所需的 JSON 对象和字段类型 |
| `invalid_citations` | 最终正文或表格包含未知或本次未获取的引用 ID |
| `insufficient_evidence` | 最终正文和表格没有引用任何有效原文证据 |

后端处理约定：

- 以 `stop_reason` 判断研究任务结果；函数正常返回不等于任务完成。`completed` 不代表已自动评估内容准确性或覆盖完整性。
- `completed` 和 `partial` 可作为正常结果展示；其他状态应同时展示停止原因和未解决项，不能仅凭 `answer` 是否非空判断成功。
- 达到执行上限或运行失败时不补最终答案；已有来源、trace 和错误记录仍保留。最终未引用的证据不会额外填入 `citations`，阅读原文等可从 trace 查看。
- `errors` 可能包含已恢复的工具错误，非空不一定表示最终失败。未知工具、禁用工具或无效参数通常返回工具错误供模型继续处理，不直接设置 `invalid_tool_call`。
- 摘要输出截断或引用无效通常作为工具错误返回；主模型输出截断才直接设置 `output_truncated`。摘要内部模型调用失败可能直接终止任务。
- 输入校验失败直接抛出 `ValidationError`；非法 arXiv 来源或非法 `context_window` 可能直接抛出 `ValueError`。调用方需捕获异常并映射为自己的错误响应；并非所有运行环境或文件错误都会包装成 `TaskResult`。
- Neon 保存失败时，结果追加 `stage="persistence"` 的错误，保留研究结果，且不改变 `stop_reason`。

错误摘要示例：

```json
{
  "errors": [
    {
      "stage": "read_paper",
      "type": "ValueError"
    }
  ]
}
```

`stage` 常见值为工具名、`model`、`model_setup`、`final` 或 `persistence`；`type` 为异常或错误类型名称。

## 4. 当前调用与取回结果

Python 调用示例，从 `agent/` 环境运行：

```python
from baseline import run_task

result = run_task(
    {
        "question": "总结这篇论文的方法和实验结果",
        "sources": ["1706.03762v7"],
    },
    persist=False,
    context_window=32000,
)
payload = result.model_dump(mode="json")
```

`run_task` 接受 `Task` 对象或字典，返回完整 `TaskResult`。

新增上下文参数均为 keyword-only 运行参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `context_window: int \| None` | `32000` | 正整数；Python 传 `None` 关闭本地上限，服务端仍校验容量 |
| `context_policy: Callable` | `prepare_context` | 替换主 agent 的输入准备策略；摘要始终使用默认 `prepare_context` 和容量检查 |

策略接口定义在 [context.py](context.py)：

```text
prepare_context(messages, *, tools, context_window, max_output_tokens, counter)
    -> PreparedContext(messages, input_tokens_estimate, count_method)
```

策略收到历史消息的副本、工具定义、容量配置和本调用流的 `TokenCounter`；返回准备后的模型输入及其估算。保存的原始历史与该输入视图分离；容量判断由调用层统一执行。当前默认实现不修改历史，未实现压缩或收尾策略。

CLI 示例，从项目根目录运行：

```bash
cd agent
uv run python baseline.py --task examples/qa.json --output runs/task-001.json
```

- `--output` 指定完整结果 JSON 文件；省略时写入 `runs/<task_id>.json`。
- `--persist` 同时保存到 Neon；不影响 CLI 写入本地结果文件。
- `--context-window INT` 配置本地窗口，默认 `32000`；关闭本地上限需使用 Python `context_window=None`。
- 标准输出只包含 `task_id/stop_reason/answer/comparison_table/unresolved/usage/errors/output`，其中 `output` 是结果文件路径。标准输出不是完整 `TaskResult`；需要引用和 trace 时，应读取结果文件。
- 退出码为 0 的条件：`stop_reason` 是 `completed` 或 `partial`，且无持久化错误；否则返回 1。输入、文件等直接抛出的异常也会导致进程失败。

## 5. 从 v0 迁移

| v0 约定 | v1 约定 |
|---|---|
| `budget` 对象 | 删除；使用任务顶层 `max_steps/timeout_seconds/max_output_tokens` |
| `budget.model_calls` | 无等价字段；`max_steps` 仅限制主 agent 轮数，不限制摘要模型调用数 |
| `budget.seconds` / `budget.output_tokens` | 对应 `timeout_seconds` / `max_output_tokens` |
| `budget.tool_calls/tokens` | 已移除，无对应限制字段 |
| `budget.context_tokens` | 已移除；本地容量检查由运行参数 `context_window` 配置，不属于任务字段 |
| `task_type` | 输入输出均已移除；任务意图由 `question` 表达 |
| `usage.budget_tokens` | 删除；新增 `usage.agent_steps` |
| `model_call_budget/tool_call_budget/token_budget/time_budget/context_budget` | 不再产生；当前执行限制或容量错误使用 `step_limit/time_limit/context_limit`，并非逐项等价替换 |
| trace 中的 `budget_remaining/estimated_input_tokens/token_estimator` | 旧字段删除；当前容量估算记录在 model/context 事件的 `context` 对象中 |
| 预留最终回答、压缩上下文、两轮无进展后收尾 | 当前无这些机制及其 trace 事件 |
| `configuration.model/temperature` 可能缺省 | 当前始终含键，未取得时为 `null` |

结果顶层移除 `task_type`，引用证据字段保持不变。v0 的最小输入仍可使用；包含 `budget` 或 `task_type` 的输入需要修改后再提交。
