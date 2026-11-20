# Agent Baseline 与 Retrieval Extension

本地 Python 3.12 + uv，模型使用百炼 `qwen3.8-27b`，与课程 TACC 包的模型标识对齐。

```bash
cd agent
uv sync --frozen
cp .env.example .env  # 首次配置；已有 .env 时直接使用
```

在 `.env` 填入百炼、Tavily key 和 Neon `DATABASE_URL`；`MODEL_BASE_URL` 使用百炼工作空间的 OpenAI 兼容地址。`uv.lock` 固定环境，`requirements.txt` 由 `uv export --no-dev --no-hashes --no-emit-project` 导出。

独立验证 API（也可直接导入这些模块）：

```bash
uv run python -m apis.model
uv run python -m apis.database
uv run python -m apis.search_web 'Attention Is All You Need arxiv' --domains arxiv.org
uv run python -m apis.papers '1706.03762' --page-start 1 --page-end 2
```

PDF 缓存在 `data/papers/`；解析保留页码、版本及原文块。设计见 [workflow](workflow.md)，任务与结果结构见 [schemas.py](schemas.py)。

运行 LangGraph baseline：

```bash
uv run python baseline.py --task examples/qa.json --persist
uv run python baseline.py --task examples/summary.json
uv run python baseline.py --task examples/review.json
uv run python baseline.py --task examples/qa.json --context-window 32000 --context-finalize-ratio 0.8
uv run pytest -q
```

Baseline 结果与 trace 写入 `runs/baseline/`；`--persist` 同时保存到 Neon。支持搜索、打开论文、分页阅读与分块摘要，输出引用保留原文和页码。`open_paper` 返回标题、版本、总页数和 PDF 书签目录，供 agent 选择阅读范围；打开、阅读与摘要共用论文缓存。

运行 Retrieval Extension 使用同一份任务 JSON：

```bash
uv run python extension.py --task examples/qa.json
```

Extension 的 `retrieve(source, query, top_k=3)` 接受单个论文标识或非空标识列表。所选论文的原文块一起排名，合计返回最多 `top_k` 个（可设为 1–5），每块保留论文标识、页码和引用 ID。例如传入两篇论文及 `top_k=3` 时，两篇合计最多返回三个块，结果可以全部来自同一篇。每次调用只为查询文本生成一个向量。

首次检索优先复用已打开的解析结果，或加载指定论文。索引按单篇论文的内容、分块与 embedding 配置缓存在 `data/retrieval/`，可跨论文组合复用；`--index-dir` 可改位置。默认使用百炼 `text-embedding-v4`、1024 维，配置见 [.env.example](.env.example)。

结果写入 `runs/extension/`。启用 `--persist` 时，Neon 存储键为 `extension/<task_id>`，结果 JSON 保留原任务 ID。Trace 中 `retrieval_index` 记录建索引或复用，`embedding` 按 `document` 和 `query` 分别记录调用耗时与实际输入 token；`usage` 延续 Baseline 的聊天模型统计。

在 `agent/` 运行 `./run.sh` 可串行对比三个示例。每个示例先跑 Baseline，再跑 Extension，各自写入对应目录的 `qa.json`、`summary.json`、`review.json`。重跑会覆盖这六个同名结果。单项失败后继续运行其余项，脚本最后以非零状态退出。

任务要求写在 `question` 中，可包含问答、总结、比较或混合要求。任务 JSON 还可设置以下执行参数：

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `max_steps` | 40 | 主 agent 最多调用轮数，包含最终答案轮；摘要调用不占此轮数 |
| `timeout_seconds` | 600 | 整任务时间上限；`null` 表示不设此上限 |
| `max_output_tokens` | 4096 | 单次模型输出额度；摘要另限制为最多 1200 |

例如在 `examples/qa.json` 的任务中加入 `"max_steps": 8, "timeout_seconds": 120`。旧版 `budget` 字段已移除，传入会报校验错误。

模型请求工具时继续循环，返回最终 JSON 时结束。到达轮数或时间上限直接记录 `step_limit` / `time_limit`，保留证据与 trace，不追加收尾调用。时间在调用前后检查，并收紧单次请求超时；它不是到点强杀。Token 用量只按 API usage 记录，不设累计额度。

每次主模型或摘要调用前，检查估算输入 token 加本次输出额度是否超过 `context_window`；超过则直接停止为 `context_limit`，不发起模型调用。窗口默认 `32000`，CLI 通过 `--context-window` 配置；Python 可传 `run_task(..., context_window=None)` 关闭本地上限。这是运行参数，不放入任务 JSON。服务端报告上下文超限时也记录 `context_limit`。

主循环先运行一次 [prepare_context](context.py)。准备后输入估算加输出额度达到窗口的 `context_finalize_ratio`（默认 `0.8`）且未超过硬上限时，改为一次无工具收尾：在该输入视图追加作答指令，再检查容量，要求基于已有证据回答并说明缺口。CLI 可用 `--context-finalize-ratio` 配置 `(0, 1]` 的比例；Python 传 `context_finalize_ratio=None` 或 `context_window=None` 禁用该触发。它不由最后一轮或剩余时间触发；如果已超过硬窗口则直接停止，不尝试收尾，超限或失败不裁剪、不重试。

默认 `prepare_context` 保留完整历史，不压缩，也不调用模型。首次计数使用字符、消息包装和工具定义估算；后续请求的历史前缀和工具定义匹配时，用 API `input_tokens` 校准并估算新增内容。主 agent 与摘要分别维护计数锚点；所有本地计数仍是近似值，实际 TACC 容量与 tokenizer 待对齐。Python 可通过 `context_policy` 替换主历史处理策略；摘要仍使用默认准备逻辑和容量检查，不触发收尾。

收尾沿用准备后的输入估算，再加新增作答指令估算；虽然实际请求不带工具，估算保留原工具定义额度，记录为 `finalize_conservative_estimate`。这是保守估算方式，不保证数学上界，也不作为 API 用量。

`usage.agent_steps` 记录主 agent 轮数，`usage.model_calls` 包含摘要调用；收尾计入两项及 API 用量，本地容量拦截不增加这两项。触发 trace 为 `kind="context", action="finalize", reason="context_pressure"`，实际收尾调用为 `purpose="finalize"`；最终 `stop_reason` 仍由回答解析、引用校验或执行错误决定。缺失的 API token 统计保留为空，不用估算补齐。原文和摘要分别按 chunk 去重，摘要后仍可读取原文核实。摘要工具的现有行为保留，后续单独评估。

代码入口是 [baseline.py](baseline.py)，按工具、模型、state、nodes、构图和运行组织。`@tool` 对象统一提供工具名称、参数和描述；当前工具节点按模型返回顺序串行执行。底层适配器在 [apis/](apis/)，任务与结果字段在 [schemas.py](schemas.py)。

切换课程服务时，在 `.env` 设置 `MODEL_PROVIDER=tacc`、`MODEL_BASE_URL=http://NODE:8000/v1`，并在平台 worker 中运行；原生工具调用需服务端支持。
