# Agent 模块对接

更新：2026-11-21。本文记录本地 baseline 的接口及其他模块的对接约定；跨模块部署尚未联调。研究流程见 [workflow](workflow.md)，具体字段见 [schemas.py](schemas.py)。

## 模块边界

| 对接方 | 提供给 agent | Agent 返回或负责 |
|---|---|---|
| Backend | 任务、可访问的论文/材料、来源范围与执行上限 | 研究结果、引用、未解决项、停止原因与 trace |
| Model serving | 本次可用 endpoint、模型配置、请求与响应约定 | Prompt、工具选择、单次输出与请求超时配置 |
| 工具与数据层 | 搜索候选、解析原文、来源定位；扩展阶段提供检索 | 查询与过滤条件、证据选择、摘要与综合 |

Backend 管任务生命周期、持久化与平台作业；agent 提供可独立运行的任务入口。当前本地 baseline 直接导入工具实现。具体由哪位组员实现适配器，在分工时确认。

暂定部署时，由 TACC 内的 agent 主动调用外部后端的论文检索、PDF 下载两个 API；具体路由、字段和鉴权待对齐，整体部署见 [系统设计](../docs/design.md)。

## 任务与证据

- 当前输入：`task_id`、`question`、arXiv ID/URL 列表 `sources`、`allow_search`、`max_papers`，以及下述执行参数。`question` 直接表达问答、总结、比较或混合要求；其他材料类型及模式切换待扩展。
- 输出：正文、比较表（适用时）、引用与证据定位、未解决项、`stop_reason` 和运行统计；运行异常单独返回错误。
- 搜索候选：来源 ID、标题、URL/文件引用、全文获取状态；仅有摘要时标明可用范围。
- 证据块：`source_id`、`paper_id`（适用时）、`chunk_id`、章节/页码、`source_text`；摘要和引用关联原文块。

材料引用必须能被实际执行 worker 读取。搜索、读取与引用均限定在任务允许的来源范围内。

执行参数位于任务顶层：`max_steps=40` 限制主 agent 调用轮数（含最终回答，不含摘要），`timeout_seconds=600` 限制任务时间（`null` 禁用），`max_output_tokens=4096` 配置单次模型输出额度。旧 `budget` 字段已移除，传入会被拒绝。到轮数或时间上限返回 `step_limit` / `time_limit`，保留已有记录，不补最终答案；时间限制通过调用前后检查和单次请求超时实现。

上下文通过运行参数配置。两版均接受 `context_window=32000`、`context_policy="full"`、`context_finalize_ratio=0.9`，对应 CLI 参数为 `--context-window`、`--context-policy full|compact` 和 `--context-finalize-ratio`。Python 也可传入自定义策略函数。

Extension 另接受布尔运行参数 `planner=False`。通过 `planner=True` 或 CLI 的 `--planner` 开启。结果在 `configuration.planner` 记录开关，在 `kind="planner"` 的 trace 记录计划及处理结果。实际调用标为 `purpose="planner"`，计入模型调用数、用量和整任务耗时。

同一入口接受独立布尔参数 `reflection=False`，对应 CLI 开关 `--reflection`。结果在 `configuration.reflection` 记录开关。自然交稿后，`kind="reflection"` 记录核对结果，`purpose="reflection"` 标记核对调用，`purpose="reflection_revision"` 标记一次补证后的无工具修订。两者均计入 `usage.model_calls` 和 API 用量，补证计入 `usage.tool_calls`。压力收尾跳过 Reflection。

主 agent 默认使用完整历史。`compact` 在估算输入加输出额度达到阈值时精简工具回包，再估算模型输入。准备后仍达到阈值且未超硬窗口时，追加一次无工具作答指令，经容量检查后收尾。准备后的输入超限则返回 `context_limit`，服务端容量错误也保留该状态。摘要使用完整输入，独立做容量检查。Python 传 `context_finalize_ratio=None` 禁用收尾，使 `compact` 仅在达到硬窗口时触发。传 `context_window=None` 则关闭本地容量触发。

首次按 ASCII 字符数 / 4、非 ASCII 字符数 × 2 估算，计入消息包装和工具定义。后续历史前缀及工具定义匹配时，用 API `input_tokens` 校准并估算新增内容。主 agent 与摘要各自维护锚点。TACC 的实际窗口、tokenizer 与消息模板待对齐。累计 token 仅记录 API usage，不参与循环控制。

模型 trace 记录 `context.window/input_tokens_estimate/count_method`。程序精简记录为 `kind="context", action="compact"`，收尾触发记录为 `action="finalize", reason="context_pressure"`。实际收尾调用记为 `purpose="finalize"`，计入主 agent 轮数、模型调用及用量。最终结果仍经解析与引用校验。[输入输出接口](agent-io-interface-v1.md)

`usage.agent_steps` 单独记录主 agent 轮数；`usage.model_calls` 包含摘要调用。API 未返回完整 token 统计时，相关总量为空并标记 `token_usage_complete=false`。每次模型与工具调用的参数、响应、耗时或错误写入 trace。

## 模型服务：当前可知信息

依据老师的 [public README](../tacc/qwen27b-student-release/README.md) 与 [客户端源码](../tacc/qwen27b-student-release/qwen-public-client/qwen_client.py)，以下是发布包约定，尚非本项目实测。

| 已知项 | 对 agent 的影响 |
|---|---|
| `POST /v1/chat/completions`，模型标识 `qwen3.8-27b` | Endpoint 每次启动后提供；模型连接参数从配置注入 |
| 文档写明 32K context、text-only | 输入材料先转文本；配置单次输出长度，实际上下文容量以服务为准 |
| 文档写明并发 4 | 第一版先串行；具体排队行为与可用并发配额待联调 |
| 请求含 `messages`、`max_tokens`、`temperature`，并发送 `enable_thinking=False` | 可先适配普通文本生成；示例默认 `max_tokens=256` 只是客户端默认值 |
| Helper 返回完整 JSON，但要求 `choices[0].message.content` 为字符串 | 适配器提取文本、结束原因与 usage；缺失统计保留为空 |
| 单次请求超时 300 秒；client job 默认 10 分钟 | Agent 另设任务超时，并据剩余时间收紧单次请求超时 |

服务与客户端是独立平台作业，service 默认 1 小时。当前客户端在作业目录执行 `main.py`；将 `agent/` 打包或安装进自有 worker job 属于后续接入工作。老师的两个发布包保持原样。部署入口见 [TACC](../tacc/README.md)。

## 模型适配与待确认项

建议先固定最小文本接口：

```text
generate(messages, max_output_tokens, temperature)
  → text, finish_reason, usage, elapsed_seconds
```

`max_output_tokens` 映射为请求的 `max_tokens`。模型返回文本仍需由 agent 校验行动格式；超时、截断与解析失败进入明确的错误或恢复路径。

接 TACC 前优先确认：

1. **工具调用协议。** 当前 helper 未提供 `tools` / `tool_choice`，也未处理纯 `tool_calls` 响应。先验证服务端原生工具调用；若暂不可用，再试验文本行动协议与参数校验。两种方式均需跑通“模型选工具 → 执行 → 回填 → 再次调用”的闭环。
2. **上下文容量。** 确认 tokenizer、实际 context/output 上限和多轮消息模板，明确工具定义、观察与输出占用。
3. **调用能力。** 确认 usage 字段、thinking 参数是否生效，以及超时和截断响应；流式与结构化输出按实际需要验证。
4. **运行位置。** 确认 backend 如何传入材料、取回产物，以及 worker 能访问的搜索、全文和数据服务。

本地 service 脚本调用平台的 `serve.sh`，完整启动参数不在发布包中。vLLM 的自动工具调用需要匹配的解析器与服务配置，详见 [v0.26.0 文档](https://docs.vllm.ai/en/v0.26.0/features/tool_calling/#automatic-function-calling)；课程实际服务配置以运行环境为准。

RAG 阶段另确认 embedding 服务、向量维度、分块与来源 ID、论文过滤条件和返回证据格式；生成模型接口本身不代表已有 embedding 能力。
