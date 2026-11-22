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

arXiv PDF 缓存在 `data/papers/`。库内 PDF 在本次任务首次打开、阅读或检索原文时下载，校验 SHA-256 后按相同规则分页、分块。设计见 [workflow](workflow.md)，任务与结果结构见 [schemas.py](schemas.py)。

运行 LangGraph baseline：

```bash
uv run python baseline.py --task examples/qa.json --persist
uv run python baseline.py --task examples/summary.json
uv run python baseline.py --task examples/review.json
uv run python baseline.py --task examples/discovery.json
uv run python baseline.py --task examples/qa.json --context-window 32000 --context-finalize-ratio 0.9
uv run pytest -q
```

后端启动后，加 `--library-login` 并按提示输入网页账号和密码，CLI 会为本次运行签发短期论文库令牌。Baseline 和 Extension 都支持。

```bash
uv run python extension.py --library-login --task examples/discovery.json
```

如需重复运行，可在本地 `agent/.env` 填写 `AGENT_LIBRARY_USERNAME` 和 `AGENT_LIBRARY_PASSWORD`。默认 API 为 `http://127.0.0.1:8000`，网页来源为 `http://127.0.0.1:5173`，自定义部署可分别设置 `AGENT_LIBRARY_BASE_URL` 和 `AGENT_LIBRARY_ORIGIN`。已有令牌也可以通过 `AGENT_LIBRARY_TOKEN` 传给不带登录参数的 CLI。[论文库 API 契约](../docs/api-contract.md#41-agent-论文库)

Python 调用按任务传入 `run_task(task, library=LibraryClient(base_url, token))`，其中 `LibraryClient` 来自 `apis.library`。`allow_search=true` 时，`search_papers` 搜 arXiv，配置了令牌的 `search_library` 按标题或文件名搜论文库。两者的候选都带有可直接交给 `open_paper(source)` 的 `source`。库内标识为 `local:<UUID>@<SHA-256>`，也可预先填入任务的 `sources`。

Baseline 结果与 trace 写入 `runs/baseline/`；`--persist` 同时保存到 Neon。支持搜索、打开论文、分页阅读与分块摘要，输出引用保留原文和页码。`open_paper` 返回标题、版本、总页数和 PDF 书签目录，供 agent 选择阅读范围；打开、阅读与摘要共用论文缓存。

运行 Retrieval Extension 使用同一份任务 JSON：

```bash
uv run python extension.py --task examples/qa.json
uv run python extension.py --task examples/summary.json --context-policy compact
uv run python extension.py --task examples/review.json --planner --context-policy full --context-finalize-ratio 0.9
uv run python extension.py --task examples/qa.json --reflection
```

Extension 默认关闭 Planner。传 `--planner` 或 Python 参数 `planner=True`，会在研究开始前做一次无工具模型调用，输出额度为 `min(256, max_output_tokens)`。主 agent 的首条任务消息先给原任务 JSON，再附上 1–3 行标为参考的建议。空计划、格式无效或规划请求失败时，主 agent 直接处理原任务。规划共用任务时限。

结果的 `configuration.planner` 记录开关。`purpose="planner"` 的模型记录可查请求、响应和用量，`kind="planner"` 的记录可查采纳的计划及处理结果。规划调用计入 `usage.model_calls` 和 API token 用量，主 agent 的 `max_steps` 单独计数。

Reflection 独立于 Planner，默认关闭。传 `--reflection` 或 Python 参数 `reflection=True` 后，主 agent 自然交稿时，模型会对照原任务、正文、比较表及其引用的原文，核实结论、比较对象和实验条件。它可以接受草稿、直接修订，或调用一次 `read_paper` / `retrieve` 补证再修订。补证后的修订调用不带工具。三条路径均经过原有引用与未解决项校验。压力收尾直接进入该校验。

结果的 `configuration.reflection` 记录开关，`kind="reflection"` 记录处理结果。核对和补证后的修订分别记为 `purpose="reflection"` 和 `purpose="reflection_revision"`。额外的 1–2 次模型调用计入聊天用量和整任务耗时，补证计入工具调用数，主 agent 轮数单独计量。若核对请求失败、超出窗口或返回无效输出，保留草稿并执行原有校验。整任务超时仍返回 `time_limit`。实测增量见[开关对照](../RESULTS.md)。

Extension 的 `retrieve(source, query, top_k=3)` 接受单个论文标识或非空标识列表。所选论文的原文块一起排名，合计返回最多 `top_k` 个（可设为 1–5），每块保留论文标识、页码和引用 ID。例如传入两篇论文及 `top_k=3` 时，两篇合计最多返回三个块，结果可以全部来自同一篇。每次调用只为查询文本生成一个向量。

同一任务中，`retrieve` 和 `read_paper` 共用已展示原文的记录。检索按原排名返回命中片段，首次命中附原文，已展示的片段只返回标识、页码和 `already_read`。全部命中都已展示时，工具结果也带有 `status: already_read`。

首次检索优先复用已打开的解析结果，或加载指定论文。索引按单篇论文的内容、分块与 embedding 配置缓存在 `data/retrieval/`，可跨论文组合复用；`--index-dir` 可改位置。默认使用百炼 `text-embedding-v4`、1024 维，配置见 [.env.example](.env.example)。

结果写入 `runs/extension/`。启用 `--persist` 时，Neon 存储键为 `extension/<task_id>`，结果 JSON 保留原任务 ID。Trace 中 `retrieval_index` 记录建索引或复用，`embedding` 按 `document` 和 `query` 分别记录调用耗时与实际输入 token；`usage` 延续 Baseline 的聊天模型统计。

从仓库根目录运行以下命令，可串行对比 `agent/examples/*.json` 下的全部示例。脚本接收一次网页账号和密码，运行 discovery 的 Baseline 和 Extension 时分别自动登录论文库。

```bash
./agent/run.sh '你的用户名' '你的密码'
```

也可通过环境变量 `AGENT_LIBRARY_USERNAME` 和 `AGENT_LIBRARY_PASSWORD` 提供凭据。省略凭据时仍运行全部示例，使用 CLI 默认的搜索配置。每个示例先跑 Baseline，再跑 Extension，分别写入 `runs/baseline/<task_id>.json` 和 `runs/extension/<task_id>.json`。示例每次生成新的任务 ID。单项失败后继续运行其余项，脚本最后以非零状态退出。

重复写入同一路径会覆盖已有结果。对照实验可用 `--output` 为每次运行指定不同的文件名。

任务要求写在 `question` 中，可包含问答、总结、比较或混合要求。任务 JSON 还可设置以下执行参数：

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `max_steps` | 40 | 主 agent 最多调用轮数，包含最终答案轮；摘要调用不占此轮数 |
| `timeout_seconds` | 600 | 整任务时间上限；`null` 表示不设此上限 |
| `max_output_tokens` | 4096 | 单次模型输出额度；摘要另限制为最多 1200 |

例如在 `examples/qa.json` 的任务中加入 `"max_steps": 8, "timeout_seconds": 120`。旧版 `budget` 字段已移除，传入会报校验错误。

模型请求工具时继续循环，返回最终 JSON 时结束。到达轮数或时间上限直接记录 `step_limit` / `time_limit`，保留证据与 trace，不追加收尾调用。时间在调用前后检查，并收紧单次请求超时；它不是到点强杀。Token 用量只按 API usage 记录，不设累计额度。

每次调用前，检查实际待发请求的估算输入加预留输出是否超过 `context_window`。容量检查失败会记录 `context_limit`。窗口默认 `32000`，CLI 通过 `--context-window` 配置，Python 可传 `run_task(..., context_window=None)` 关闭本地上限。这是运行参数，不放入任务 JSON。服务端报告上下文超限时也记录 `context_limit`。

两版均可用 `--context-policy full|compact` 或 Python 的 `context_policy` 选择主 agent 的输入视图。默认 `full` 保留完整历史。`compact` 在估算输入加输出额度达到窗口的 90% 时，以程序精简重复的原文块、已有选文的搜索回包及空读记录。每个唯一原文块保留一份完整文本，工具调用与返回保持配对。原始历史和工具 trace 保留，精简不调用模型。分块摘要始终使用完整输入。[策略实现](context.py)

用 `--context-finalize-ratio` 调整同一个压力阈值。准备后的输入加输出额度达到或超过阈值即进入一次无工具收尾，包括单轮越过硬窗口的情况。Python 传 `context_finalize_ratio=None` 关闭压力收尾，此时 `compact` 仅在达到硬窗口时尝试精简。传 `context_window=None` 则关闭本地容量触发。

首次计数按字符、消息包装和工具定义估算。历史前缀和工具定义匹配时，用 API `input_tokens` 校准并估算新增内容。改写历史可能使估算回退到字符法。主 agent 与摘要分别维护计数锚点，实际 TACC 容量与 tokenizer 待对齐。

收尾先沿用准备后的估算并计入作答指令（`finalize_conservative_estimate`）。若超窗，按无工具请求重新估算（`heuristic`）。若仍超窗，保留系统指令、用户任务与输出额度，优先从最近的工具结果选入放得下的完整原文块和摘要。最小请求仍超窗时返回 `context_limit`。

`usage.agent_steps` 记录主 agent 轮数，`usage.model_calls` 包含摘要调用；收尾计入两项及 API 用量，本地容量拦截不增加这两项。触发 trace 为 `kind="context", action="finalize", reason="context_pressure"`，实际收尾调用为 `purpose="finalize"`；最终 `stop_reason` 仍由回答解析、引用校验或执行错误决定。缺失的 API token 统计保留为空，不用估算补齐。原文和摘要分别按 chunk 去重，摘要后仍可读取原文核实。摘要工具的现有行为保留，后续单独评估。

代码入口是 [baseline.py](baseline.py)，按工具、模型、state、nodes、构图和运行组织。`@tool` 对象统一提供工具名称、参数和描述；当前工具节点按模型返回顺序串行执行。底层适配器在 [apis/](apis/)，任务与结果字段在 [schemas.py](schemas.py)。

切换课程服务时，在 `.env` 设置 `MODEL_PROVIDER=tacc`、`MODEL_BASE_URL=http://NODE:8000/v1`，并在平台 worker 中运行；原生工具调用需服务端支持。
