# 论文研究 Agent

Agent 根据研究问题选择论文、读取 PDF，并把答案中的论断关联到可回看的原文片段。Baseline 实现 LangGraph 的 ReAct 循环。Retrieval Extension 复用同一循环，增加段落检索工具，并可独立开启 Planner 和 Reflection。两者接受相同的任务，输出相同的结果结构。

[工作流](#agent-workflow) · [本地运行](#本地运行) · [任务与结果接口](#任务与结果接口) · [消融实验复现](#消融实验复现) · [报告指标](#从输出填写报告)

## Agent workflow

![Baseline 研究循环与 Extension 的规划、段落检索和草稿核对路径](workflow.png)

上栏是 Baseline，下栏用蓝色标出 Extension 增加的部分。ReAct 循环由 `agent` 和 `tools` 两个节点组成。可选的 `planner` 在循环前运行，`reflection` 在循环外接收有效草稿（含上下文压力收尾的草稿），需要时可调用一次 `read_paper` 或 `retrieve` 补证。虚线表示跳过对应节点的路径。[报告用 SVG 矢量图](workflow.svg)

### Baseline 如何从问题走到引用

1. **确定来源。** Agent 从预选论文出发。若任务允许搜索，它也可从 arXiv 或已授权的用户论文库发现候选。搜索返回的 `source` 可交给任何阅读工具。
2. **收集证据。** 主模型根据问题和已有工具结果决定下一步。它可以先浏览目录选页，也可以直接精读或请求分块摘要。工具节点按请求顺序执行，用 PyMuPDF 从 PDF 提取带页码的原文块，将观察结果交回主模型。只要还有预算，模型可据此继续阅读。
3. **提交答案。** 模型交付正文、可选比较表和未解决项。程序从本次任务登记的原文中匹配正文与表格引用的 `chunk_id`，返回对应片段、论文版本和 PDF 页码。论断是否得到该片段支持，还需对照原文判断。[研究循环与引用校验](baseline.py) · [PDF 分页与分块](apis/papers.py)

### Extension 在何时介入

| 模块 | 介入时机与行为 | 在 trace 中核实 |
|---|---|---|
| Planner | 开启 `--planner` 后，研究开始前做一次无工具调用。有效的 1–3 行建议附在原任务后。空计划、无效输出或规划请求失败时，主循环仍可处理原题。整任务超时则停止。 | `kind=planner` 的 `outcome` 与 `plan` 区分实际采用的建议和空计划。 |
| RAG | 主模型可按子问题调用 `retrieve`。首次检索时逐篇建立或复用本地索引，每次为查询生成一个向量，按余弦相似度从所选论文中合并取前 `top_k` 块。同一次跨篇检索可以全部命中同一篇论文。 | `kind=tool, name=retrieve` 给出查询、论文和命中片段。`retrieval_index` 区分 `build` / `reuse`，`embedding` 区分文档和查询开销。 |
| Reflection | 开启 `--reflection` 后，主模型每次提交字段有效的草稿（包括上下文压力下的提前交稿），都会触发一次独立核查，输入包含原问题、草稿和所引原文。可接受、直接修订，或用一次 `read_paper` / `retrieve` 补证后无工具修订。核查失败时保留草稿进入公共校验，整任务超时记为 `time_limit`。 | `kind=reflection` 的 `outcome` 给出处理结果。补证后的模型调用标为 `purpose=reflection_revision`。 |

Planner 和 Reflection 默认均关闭。是否启用见结果的 `configuration`，实际执行路径见 trace。[Extension 实现](extension.py) · [索引与排序](retrieval.py)

**以预选论文 QA 为例。** 在首批消融（`20261123T004926Z-t2jtjsvv`）中，Baseline 先打开《Attention Is All You Need》的目录，再分别读第 4、5 页。RAG 直接按问题检索，第一个命中就是第 4 页解释缩放因子的原文。随后它又请求第 4 页，工具返回 `already_read`。两份答案最终都引用了 `arxiv:1706.03762v7:p4:c1`。在同批次的 `qa/baseline/` 和 `qa/rag/` 下可核对工具顺序与最终引用。[该题输入](examples/qa.json)

### 上下文压力与停止

主模型每轮先估算输入（含工具定义），加上本次预留的输出额度，与默认 32,000 token 的窗口比较。`full` 保留完整历史。`compact` 达到阈值时先精简重复工具回包，保留原始 trace。准备后的请求仍达到阈值（默认 90%）时，两版均转入一次无工具作答。开启 Reflection 时，有效草稿先进入核查，再校验最终引用。若请求已超窗，程序按无工具请求重估，必要时优先装入最近可容纳的完整原文块和摘要。最小请求仍超窗则返回 `context_limit`。[上下文策略](context.py)

trace 中的 `kind=context, action=finalize` 表示触发收尾，`purpose=finalize` 表示实际发起模型调用。引用校验决定最终状态，压力收尾也可能得到 `completed` 或 `partial`。轮数用尽或任务超时则直接记录 `step_limit` / `time_limit`，保留已有 trace。

## 本地运行

准备 uv 和 Python 3.12，从仓库根目录执行以下命令。uv 按锁文件安装依赖，首次配置时复制环境变量模板。[依赖锁文件](uv.lock)

```bash
cd agent
uv sync --frozen
test -f .env || cp .env.example .env
```

在 `.env` 填入 `BAILIAN_API_KEY`，确认 `MODEL_BASE_URL` 是该工作空间的 OpenAI 兼容端点，`MODEL_NAME` 默认 `qwen3.8-27b`。下面的 Baseline 示例预选了《Attention Is All You Need》v7。首次运行需能从 arXiv 下载 PDF，之后复用 `data/papers/1706.03762v7.pdf`。[环境变量示例](.env.example)

```bash
uv run --frozen python baseline.py --task examples/qa.json
```

终端输出 `stop_reason`、`answer`、`usage` 和结果文件路径 `output`。打开 `runs/baseline/<task_id>.json` 可查看完整 `trace` 和 `citations`。这道题跑通时，应能在答案中找到缩放因子与 softmax 梯度的关系，并用引用的 `page`、`source_text` 回到 PDF 核对。固定输出路径可加 `--output runs/qa.json`，再次写入该路径会覆盖文件。

同一份任务可交给 Extension，结果写入 `runs/extension/<task_id>.json`。以下命令仍在 `agent/` 执行。

```bash
uv run --frozen python extension.py --task examples/qa.json --planner --reflection
uv run --frozen python baseline.py --task examples/library-qa.json --library-login
uv run --frozen pytest -q
```

- 带 arXiv 搜索的本地任务使用 `TAVILY_API_KEY`。库内任务需要运行论文库 API，`--library-login` 使用网页账号签发短期令牌。也可在环境中设置 `AGENT_LIBRARY_TOKEN` 后直接运行。自定义部署通过 `AGENT_LIBRARY_BASE_URL` 与 `AGENT_LIBRARY_ORIGIN` 指定 API 和网页地址。[本地服务启动](../docs/service_launch.md#按系统使用脚本)
- Extension 调用 `retrieve` 时需要百炼嵌入服务，默认 `text-embedding-v4`、1024 维。索引缓存在 `data/retrieval/`，可用 `--index-dir` 改位置。课程聊天模型用 `MODEL_PROVIDER=tacc` 和 `MODEL_BASE_URL` 指向可达的课程端点，用 `EMBEDDING_BASE_URL` 单独指定百炼嵌入端点。[课程模型服务](../model-server/README.md)
- 需要同时写入 PostgreSQL（如 Neon）时，设置 `DATABASE_URL` 并加 `--persist`。各适配器也可单独运行，例如 `uv run --frozen python -m apis.model` 检查模型，`uv run --frozen python -m apis.papers 1706.03762v7 --page-start 4 --page-end 4` 核对 QA 引用的原文。[适配器](apis/)

## 任务与结果接口

Baseline 与 Extension 接受同一个 `Task` 对象或字典，返回 `TaskResult`。下面的 Python 示例可在 `agent/` 的 uv 环境运行。使用论文库时向 `run_task` 传 `library=LibraryClient(base_url, token)`，客户端来自 `apis.library`。[字段定义](schemas.py) · [论文库鉴权](../docs/api-contract.md#41-agent-论文库)

```python
from baseline import run_task

result = run_task({"question": "为什么缩放点积注意力要除以 √dₖ？", "sources": ["1706.03762v7"]})
payload = result.model_dump(mode="json")
```

| 任务字段 | 默认值 | 约定 |
|---|---|---|
| `question`、`task_id` | 问题必填，ID 自动生成 | 问答、总结、比较等要求直接写入 `question`。自定义 ID 长 1–101，以字母或数字开头，其余可含 `.`、`_`、`-` |
| `sources`、`allow_search` | `[]`、`false` | 来源支持 arXiv ID/URL 或 `local:<UUID>@<SHA-256>`。关闭搜索时至少给一个来源 |
| `max_papers` | `3` | 取 1–20，按实际获取的不同论文计数。搜索返回候选时不占额度 |
| `max_steps` | `40` | 主 Agent 模型轮数上限，含最终作答轮。最后一轮仍请求工具时立即返回 `step_limit` |
| `timeout_seconds` | `600` | 整任务时限，`null` 取消本地整任务时限。调用前后检查，单次请求按剩余时间收紧 |
| `max_output_tokens` | `4096` | 单次聊天输出上限。分块摘要每次至多 1200，Planner 至多 256，两者仍受任务设定约束 |

输入拒绝未声明的字段。旧输入中的 `task_type` 应改写到 `question`，`budget` 应改为上述顶层参数。运行参数 `context_window`、`context_policy`、`context_finalize_ratio` 对应 CLI 的 `--context-window`、`--context-policy`、`--context-finalize-ratio`。Python 传 `context_window=None` 可关闭本地容量检查与压力收尾，仅关闭压力收尾可用 `context_finalize_ratio=None`。Extension 额外接受 `planner`、`reflection`、`index_dir`。

### 工具与引用

模型可以把预选来源、搜索候选的 `source` 或已打开论文的 `source_id` 交给阅读工具。页码从 1 起，页段包含首尾两页。[基础工具](baseline.py) · [检索工具](extension.py)

| 工具 | 输入 | 返回给模型的内容 |
|---|---|---|
| `search_papers` | `query` | 获准搜索时通过 Tavily 查 arXiv，最多 5 条候选，含 `source/title/url/snippet` |
| `search_library` | 可选 `query`、`match`（`all` 或 `any`）、`offset` | 获准搜索且配置论文库时可用，按标题或文件名匹配，每页至多 5 条，含 `source/title/original_filename` 和分页信息 |
| `open_paper` | `source` | `source_id`、标题、版本、页数和 PDF 书签目录，供选择阅读范围 |
| `read_paper` | `source, page_start, page_end`，1–3 页 | 新读原文块和已读块 ID，全段已读时返回 `already_read` |
| `summarize_paper` | 同上，1–6 页 | 按批返回带片段引用的摘要及对应 `chunk_ids`。摘要单独去重，之后仍可读取原文 |
| `retrieve`（Extension） | `source`（一个标识或非空列表）、`query`、`top_k`（默认 3，范围 1–5） | 在指定论文间统一排名，合计至多 `top_k` 个命中。与 `read_paper` 共用已读记录，重复命中返回 ID、页码和 `already_read` |

搜索结果仅供发现，目录仅供导航。阅读、摘要、检索登记可引用的原文块。正文与比较表使用工具提供的 `[chunk_id]`，例如 `[arxiv:1706.03762v7:p4:c1]`。`citations` 按正文、表格中的首次出现顺序返回实际引用的有效块，每条保留 `chunk_id, source_id, paper_id, version, page, source_text, url, title`。

### 结果、状态与 trace

`TaskResult` 包含 `task_id, question, answer, comparison_table, citations, unresolved, stop_reason, usage, sources, trace, errors, configuration`。`sources` 列出本次实际获取的论文。`configuration` 保留补齐默认值的任务、模型、温度和上下文参数。Extension 还记录 `workflow, embedding_model, planner, reflection`。

| `stop_reason` | 解释 |
|---|---|
| `completed` / `partial` | 回答结构和引用检查通过。`unresolved` 为空时为 `completed`，有未解决项时为 `partial`。科学结论和比较方向仍需对照原文核实 |
| `step_limit` / `time_limit` / `context_limit` | 达到主循环轮数、整任务时间或单次请求容量限制 |
| `invalid_citations` / `insufficient_evidence` | 正文或表格引用了未登记的块，或整份答案没有有效原文引用 |
| `model_error` / `invalid_tool_call` / `output_truncated` / `invalid_output` | 模型设置或调用失败、工具调用无法解析（或收尾仍要求工具）、主回答截断、最终 JSON 不合约定 |

`usage.agent_steps` 计主循环及压力收尾轮数，`model_calls` 还计入摘要、规划和反思的聊天调用。`tool_calls` 计已尝试执行的工具。聊天 API 缺少完整用量时，`input_tokens/output_tokens/total_tokens` 为 `null`，`token_usage_complete=false`。`usage.elapsed_seconds` 是研究任务总耗时。摘要工具耗时包含内部模型调用，同一任务的 trace 耗时有重叠。

`trace` 按执行顺序保存事件。查 `kind="model"` 的 `purpose/messages/response` 可重建一次模型决策，失败时查 `error`。查 `kind="tool"` 的 `name/arguments/observation` 可追溯实际读到的证据。`context` 事件记录压缩、压力收尾或容量拦截。Extension 另有 `planner/reflection/retrieval_index/embedding` 事件，嵌入用量在 `embedding` 事件中单记。`errors` 保存阶段和错误类型，也可能包含已恢复的工具错误。

### 本地与平台交付

- **单次 CLI** 写入完整 `TaskResult`，可选数据库键为 Baseline 的 `task_id` 或 Extension 的 `extension/<task_id>`。`completed` 或 `partial` 且无持久化错误时退出码为 0。输入校验失败可能发生在生成结果文件之前。
- **网页 / TACC** 由后端冻结任务和运行配置。`tcloud` 的 `input.zip` 内含 `manifest.json`、`task.json`、`sources.json`，作业使用另发的只读令牌从后端取预选 PDF，并核对原件摘要。兼容传输 `manual/local/tacc` 的包另附 `papers/<UUID>.pdf`。作业写 `status.json` 和 `result.json`，后者是 `agent-result-v1` 信封，含 `dispatch_id, input_sha256, remote_job_id, result`。Worker 校验派发身份与证据后入库。网页作业的 `succeeded` 同时涵盖研究结果 `completed` 和 `partial`。[派发协议](../docs/api-contract.md#7-agent-派发协议) · [作业入口](../tacc/research/run_job.py) · [模型服务](../model-server/README.md)

## 消融实验复现

用实验账号登录网页，将首批使用的 SkillOpt 原始 PDF 上传至论文库，确认输入 `SkillOpt` 可搜到。各配置共用同一模型端点、账号与论文库。配置好聊天、搜索和嵌入服务，在 `agent/.env` 填入 `AGENT_LIBRARY_USERNAME` 与 `AGENT_LIBRARY_PASSWORD`，再从**仓库根目录**执行以下命令。[SkillOpt 原文 v2（PDF）](https://arxiv.org/pdf/2605.23904v2)

```bash
./agent/run.sh
```

也可向脚本传入用户名和密码两个参数，或使用已有的 `AGENT_LIBRARY_TOKEN`。使用账号时可为后续库内问答和 discovery 重新签发短期授权。脚本先检查 SkillOpt 搜索结果，再按表中顺序逐题跑完五种配置。同题共用任务 JSON 和预算（默认 40 轮、600 秒、每次输出 4096 token）。聊天调用为非流式，温度为 0。上下文策略为 `full`，窗口 32,000，收尾阈值为 90%。[批跑脚本](ablation.py) · [聊天模型配置](apis/model.py)

| 案例 | 数据与范围 | 报告中核对的问题 |
|---|---|---|
| [`library-qa`](examples/library-qa.json) | 空预选，仅要求访问自己的库，最多 1 篇 | 是否经 `search_library` 找到 SkillOpt 原文。优化对象、保留更新的判据是否各有页码证据 |
| [`qa`](examples/qa.json) | 预选 `1706.03762v7`，关闭搜索 | 是否用原文解释点积规模、softmax 梯度与缩放因子的关系 |
| [`summary`](examples/summary.json) | 同一预选论文，关闭搜索 | 研究问题、方法、翻译结果、适用条件与未覆盖内容是否交代清楚 |
| [`review`](examples/review.json) | 空预选，搜索 LoRA、QLoRA 原论文，最多 2 篇 | 比较表中的方法、显存机制、数字与实验条件是否有逐项支持。若引用 WikiSQL，核对数值和比较方向 |
| [`discovery`](examples/discovery.json) | 空预选，可搜 arXiv 与本库，最多 5 篇 | 代表工作是否有原文证据，是否解释如何用经验更新技能 |

| 配置目录 | 入口 | RAG 工具 | Planner | Reflection |
|---|---|---|---|---|
| `baseline` | `baseline.py` | 关 | 关 | 关 |
| `rag` | `extension.py` | 开 | 关 | 关 |
| `rag-planner` | `extension.py` | 开 | 开 | 关 |
| `rag-reflection` | `extension.py` | 开 | 关 | 开 |
| `full` | `extension.py` | 开 | 开 | 开 |

每次新建 `agent/runs/ablation/<批次>/<案例>/<配置>/`。终端显示批次目录、当前组号和停止原因。每组将结果写入 `result.json`，事件序列单独写入 `trace.json`。单组出错后继续执行，其余组仍可比较。跑完 25 组时，`completed` 和 `partial` 计为已交稿，其他停止原因计入失败数且批次退出码为 1。若运行器在产生结果前抛出异常，该组保留 `runner_error` 和错误类型，trace 为空。

### 从输出填写报告

以「批次、案例、配置」定位一行，同题横向比较。Baseline 与 `rag` 使用各自的研究提示词。`rag-planner`、`rag-reflection` 与 `rag` 的对照分别观察两个开关的增量。一次批次中每个组合只有一次运行，复跑时保留批次标识。

| 报告列 | 从哪里取，如何判读 |
|---|---|
| 完成状态与缺口 | 从 `result.json` 取 `stop_reason`、`unresolved`、`errors`，分别列出完整交稿、部分交稿和失败。 |
| 答案正确性 | 按上表逐项核对 `answer`、`comparison_table` 与原论文，记录答对、遗漏和答错的要点。 |
| 引用支持 | 用 `citations[].source_text`、`source_id` 和 `page` 逐条核对正文论断、表格单元格中的 `[chunk_id]`。报告“有直接原文支持的项数 / 应提供证据的项数”，分母包括缺少引用的项。 |
| 时间与用量 | 整项耗时取 `usage.elapsed_seconds`，聊天用量取 `usage.input_tokens`、`output_tokens`、`total_tokens`，并列 `agent_steps`、`model_calls`、`tool_calls`。`token_usage_complete=false` 或缺失的指标标作缺失。嵌入用量从 trace 的 `kind=embedding` 按 `purpose=document/query` 分列 `input_tokens`。 |
| 组件是否介入 | 在 `trace.json` 查 `kind=tool, name=retrieve` 的参数、命中和来源，`kind=retrieval_index` 的 `action=build/reuse` 可解释冷、热缓存差异。`kind=planner` 的 `outcome=used` 表示采用计划，`empty` 表示没有建议。`kind=reflection` 的 `outcome` 记录核对结果。开启反思后，正常交稿和压力收尾产生的有效草稿都应出现反思事件。缺少事件时，先检查主模型是否交出了有效草稿。 |
