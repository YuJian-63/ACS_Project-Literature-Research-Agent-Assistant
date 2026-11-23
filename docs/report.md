# 全流程研究实验报告

本报告分析 `Researcher` 账号在 **2026 年 11 月 23 日 07:30–09:01（Asia/Shanghai）**提交的研究任务。指标快照提取于当日 **10:27:35**；重跑步骤、论文版本、预算和命令见[根 README 的 Evaluation](../README.md#evaluation)，原始问题、PDF 哈希、完整任务 ID、固定评分版本和脱敏指标见[实验清单](evaluation/researcher-20261123.json)。本报告比较 Agent Baseline 与 Extension；独立的模型服务原版/优化版实验见 [Server report](../model-server/server-opt/reports/Server_report.md)。

## 1. 样本与比较边界

快照包含 36 个任务：Baseline 15 个、Extension 21 个。按**相同问题与相同初始 PDF 哈希集合**匹配得到 15 对，覆盖问答 3 对、摘要 3 对、综述 4 对、调研 5 对；其余 6 个 Extension 运行单列。每例每种模式只有一次运行，没有重复实验或置信区间。

**全部 36 个任务的后端状态为 `succeeded`，但 Agent 停止原因均为 `partial`。**这说明平台成功交付了结果，不代表完整完成研究要求。以下性能与评分描述的是这些部分结果，不是完整任务成功率；不能将后端交付率当作研究完成率。

共同配置为课程 `qwen3.8-27b`、温度 0、32,000 Token 上下文、CompactHistory、0.9 收尾阈值、单次最大输出 16,384 Token、允许追加检索 5 篇。实际步数与时限随预选论文数变化，见 README。各配对的服务 generation 和配置预算一致，但全部样本跨越两轮服务；完整历史模型服务启动配置与逐任务代码提交未归档。清单的 `serving_revision_at_capture` 仅为提取时部署版本，不能当作每个任务的执行版本。

Extension 配置启用了 Planner 和 Reflection；21 个 Extension trace 均出现 Planner 调用，**全部样本均没有 `retrieve` 工具调用，也没有 Reflection 模型调用**。因此，本轮仅能比较实际执行的两种工作流，不能声称验证了向量检索或 Reflection 的收益，也不能把差异单独归因于某个模块。

### 表 E1：配对用例与评分版本

任务 ID 为前 8 位，完整 ID 见清单。评分栏统一为 **Baseline → Extension**。`v1` / `v2` 分别表示 `deepseek-judge-v1` / `deepseek-judge-v2`；版本不同的配对仍用于性能统计，但不进入主要质量均值。

| 用例 | 问题主题 | 任务 ID（B / E） | 原始总分（B → E） | 评分版本（B / E） | 主要质量比较 |
| --- | --- | --- | --- | --- | --- |
| QA01 | FlashAttention-2 arithmetic complexity | `73285532` / `9e343362` | 78 → 91 | v1 / v1 | 纳入 |
| QA02 | Longformer local and global attention | `14323715` / `68ad2413` | 78 → 84 | v1 / v1 | 纳入 |
| QA03 | Performer approximation versus exact attention | `551a240b` / `02c0db2f` | 80 → 67 | v1 / v1 | 纳入 |
| SUM01 | Transformer architecture and experimental evidence | `ab6cd2a4` / `37494825` | 79 → 79 | v1 / v1 | 纳入 |
| SUM02 | Transformer translation results and limitations | `b9593597` / `366521aa` | 69 → 85 | v1 / v1 | 纳入 |
| SUM03 | FlashAttention method and evidence | `719e5839` / `459e1f33` | 81 → 81 | v2 / v2 | 纳入 |
| REV01 | Three linear-attention approaches | `cb74f670` / `b7f24304` | 81 → 56 | v1 / v2 | 排除：版本不同 |
| REV02 | Five efficient-attention papers | `d62a3361` / `ac042b95` | 66 → 66 | v1 / v2 | 排除：版本不同 |
| REV03 | Detailed FlashAttention GPU mechanisms | `eda46618` / `ddf53e81` | 55 → 65 | v1 / v1 | 纳入 |
| REV04 | Two-paper FlashAttention overview | `129c8e3d` / `d3ce25b3` | 85 → 81 | v2 / v2 | 纳入 |
| SUR01 | LoRA and QLoRA memory reduction | `6b91d9a7` / `00b049f4` | 85 → 83 | v2 / v1 | 排除：版本不同 |
| SUR02 | Self-evolving Agent skills | `ce649bf1` / `b3ebadb8` | 69 → 73 | v2 / v2 | 纳入 |
| SUR03 | Sparse attention for long documents | `aaf2d28a` / `b86a2e5d` | 65 → 73 | v2 / v1 | 排除：版本不同 |
| SUR04 | Hallucination detection and reduction | `f2222697` / `2892a727` | 68 → 73 | v2 / v2 | 纳入 |
| SUR05 | Retrieval-augmented knowledge-intensive QA | `9d3c0f51` / `9aa1af2d` | 71 → 74 | v1 / v2 | 排除：版本不同 |

`REV01`、`REV02`、`REV03` 两侧的论文集合相同但输入顺序不同；表中的比较未消除此项干扰。领域调研均从空预选集合开始，动态搜索和后续选文可能不同。

## 2. DeepSeek 质量评分

评分模型为 `deepseek-flash`，rubric 为 `research-v1`。五维各 0–5 分，权重依次为事实与证据一致性 30、引用支持 30、任务完成度 20、分析质量 15、表达清晰度 5；总分为 `Σ(维度分 × 权重 / 5)`。评分是模型判定，未以人工标注校准。

### 表 E2：同评分版本配对的质量均值

仅纳入两侧评分成功、`assessment=scored` 且评分模型、rubric、提示词版本和权重一致的 **10 对**。同一对版本相同不代表跨用例版本相同，故仍需结合下方版本分层解读。

| 类型 | 配对数 | 总分 / 100 | 事实与证据 / 5 | 引用支持 / 5 | 完成度 / 5 | 分析质量 / 5 | 清晰度 / 5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 单论文问答 | 3 | 78.67 → 80.67 | 4.00 → 4.33 | 3.33 → 3.33 | 4.67 → 4.67 | 4.00 → 4.00 | 4.00 → 4.00 |
| 单论文摘要 | 3 | 76.33 → 81.67 | 4.00 → 4.00 | 3.00 → 3.67 | 4.33 → 4.67 | 4.00 → 4.00 | 5.00 → 5.00 |
| 多论文综述 | 2 | 70.00 → 73.00 | 3.50 → 3.50 | 3.00 → 3.50 | 4.00 → 4.00 | 3.50 → 3.50 | 4.50 → 4.50 |
| 领域调研 | 2 | 68.50 → 73.00 | 4.00 → 4.00 | 3.50 → 4.00 | 2.50 → 3.00 | 3.00 → 3.00 | 4.50 → 4.00 |

10 对的描述性总均值为 **74.20 → 77.90**。按提示词版本分层：v1 的 6 对为 **73.17 → 78.50**，v2 的 4 对为 **75.75 → 77.00**。两组包含不同问题，不能据此认定某版本更严格或直接比较两版本的绝对分数。

摘要中引用支持与完成度均值上升；综述和调研的可比较子集中引用支持也上升，但样本均只有 2 对。问答差异不一致：`QA01` 为 78 → 91，`QA02` 为 78 → 84，`QA03` 为 80 → 67，因此不能概括为 Extension 对每个问题都更好。所有任务的 `partial` 状态同样限制了对质量提升的解释。

## 3. 耗时、步骤与聊天 Token

本节使用全部 **15 对**。每个类型先分别计算 Baseline / Extension 的逐任务算术均值，所有箭头均为 Baseline → Extension。相对变化为 `(Extension / Baseline − 1) × 100%`，负值表示下降。

### 表 E3：平台端到端与 Agent 自身耗时

平台耗时为创建至结束，包含派发、TACC 排队/启动及回传，不含独立评分；Agent 耗时来自 `usage.elapsed_seconds`，不含平台等待。

| 类型 | 配对数 | 端到端（秒） | Agent（秒） | Agent 耗时变化 |
| --- | --- | --- | --- | --- |
| 单论文问答 | 3 | 139.79 → 245.37 | 70.03 → 77.95 | +11.31% |
| 单论文摘要 | 3 | 160.70 → 265.00 | 107.33 → 113.94 | +6.17% |
| 多论文综述 | 4 | 181.84 → 263.43 | 113.77 → 98.27 | -13.62% |
| 领域调研 | 5 | 217.67 → 284.55 | 73.04 → 65.34 | -10.54% |

Extension 的综述和调研 Agent 耗时分别下降约 13.62% 和 10.54%，问答和摘要则增加。**四类任务的端到端耗时均增加**，因此不能用 Agent 内部耗时下降来宣称用户等待时间缩短。现有数据没有将 TACC 等待、环境启动及回传逐项隔离，不能确定每项对差异的贡献。

### 表 E4：Agent 步数与调用次数

| 类型 | Agent 步数 | 模型调用次数 | 工具调用次数 |
| --- | --- | --- | --- |
| 单论文问答 | 3.67 → 4.33 | 3.67 → 5.33 | 3.33 → 4.00 |
| 单论文摘要 | 4.00 → 4.00 | 4.00 → 5.00 | 4.67 → 4.67 |
| 多论文综述 | 5.00 → 4.00 | 5.00 → 5.00 | 7.50 → 7.00 |
| 领域调研 | 5.40 → 5.20 | 5.40 → 6.20 | 11.60 → 10.80 |

模型调用数不必等于 Agent 步数；例如 Extension 的 Planner 也计入聊天模型调用。本轮没有实际 Reflection 调用。综述的平均步数减少，但加入 Planner 后模型调用数仍为 5.00 → 5.00。

### 表 E5：聊天 Token 用量

| 类型 | 输入 Token | 输出 Token | 总 Token | 总 Token 变化 |
| --- | --- | --- | --- | --- |
| 单论文问答 | 23,281.7 → 30,748.3 | 3,462.0 → 3,680.7 | 26,743.7 → 34,429.0 | +28.74% |
| 单论文摘要 | 30,115.7 → 31,095.3 | 5,427.3 → 5,767.3 | 35,543.0 → 36,862.7 | +3.71% |
| 多论文综述 | 30,869.2 → 34,067.2 | 5,783.2 → 4,680.0 | 36,652.5 → 38,747.2 | +5.72% |
| 领域调研 | 39,079.4 → 35,456.0 | 2,871.2 → 2,614.6 | 41,950.6 → 38,070.6 | -9.25% |

以上是聊天调用累计 Token，包含每次调用重复送入的上下文，不包含独立 DeepSeek 评分和另行记录的 Embedding 消耗，不能等同于完整系统费用。任务 Token 统计均标记为完整。调研的聊天 Token 下降，但问答、摘要和综述上升；本轮不存在普遍的 Token 节约结论。

## 4. 模型服务遥测与缓存

所有任务均有模型服务指标。TTFT 采用原生 `metrics.time_to_first_token_ms`，TPOT / mean ITL 采用 `metrics.mean_itl_ms`，tokens/sec 采用 `metrics.tokens_per_second`。先由后端对单任务中同来源有效请求求均值，再对同类型任务均值求算术平均；不是将所有请求混在一起加权，也不是固定负载吞吐测试。

### 表 E6：原生请求性能的任务宏平均

| 类型 | TTFT（毫秒） | TPOT / mean ITL（毫秒） | 输出 tokens/sec |
| --- | --- | --- | --- |
| 单论文问答 | 3,526.30 → 3,104.85 | 15.66 → 15.62 | 48.89 → 37.40 |
| 单论文摘要 | 4,311.90 → 3,606.58 | 15.70 → 15.70 | 46.28 → 37.51 |
| 多论文综述 | 4,148.81 → 3,876.05 | 15.74 → 15.69 | 49.01 → 40.58 |
| 领域调研 | 3,169.83 → 2,287.60 | 15.77 → 15.67 | 39.52 → 37.70 |

Extension 的任务宏平均 TTFT 在四类中均更低，但输出 tokens/sec 也均更低，TPOT 变化很小。Planner 等短调用改变了请求组成；缓存、共享负载及输出长度也会影响这些统计。因此不能将 TTFT 下降解释为模型引擎加速，tokens/sec 也不能作为完整研究任务吞吐量。

### 表 E7：缓存 Token 与组级命中率

命中/查询 Token 为逐任务均值；组级命中率为 `Σ命中 Token / Σ查询 Token`，而非逐任务比例的平均。所有样本的缓存覆盖均标记完整。

| 类型 | 平均命中 Token | 平均查询 Token | 组级命中率（B → E） |
| --- | --- | --- | --- |
| 单论文问答 | 4,965.3 → 7,056.0 | 23,281.7 → 30,748.3 | 21.33 → 22.95% |
| 单论文摘要 | 5,488.0 → 5,488.0 | 30,115.7 → 31,095.3 | 18.22 → 17.65% |
| 多论文综述 | 7,252.0 → 6,860.0 | 30,869.2 → 34,067.2 | 23.49 → 20.14% |
| 领域调研 | 15,052.8 → 15,993.6 | 39,079.4 → 35,456.0 | 38.52 → 45.11% |

调研组命中率由 38.52% 升至 45.11%，问答略升，摘要与综述下降。本轮未控制冷/热缓存与任务先后顺序，因此这些数值只是运行观察，不能单独证明工作流提高了缓存效率。

每个任务均保存两张 GPU 的最近完成时快照，利用率读数均为 **99%**。这些是已分配设备的共享快照，包含其他进程，既不是本任务的均值也不是峰值；本轮无法据此区分两种工作流的 GPU 利用效率。

## 5. 未配对与缺失数据

以下 6 个 Extension 运行保留在清单中，但没有相同问题及论文集合的 Baseline，不进入配对均值。它们也均为 `partial`。其中两个长上下文调研是重复 Extension 运行，不能将其互相当成 Baseline / Extension。

| 任务 ID | 问题主题（原始问题首句） | 最新评分总分 / 100 |
| --- | --- | --- |
| `a0ba27c2-b130-43ab-885d-fcd10c48b887` | Survey three to five research papers on hardware-aware attention optimization, including at least one FlashAttention paper | 69 |
| `37210b34-49a7-40e1-8b2d-ec313c5151e9` | Write a comparative review of Longformer and Big Bird | 缺失（`EVALUATION_INVALID_RESPONSE`） |
| `fe271bd7-e589-46a2-9095-8c561948ef27` | Investigate linear-attention methods for autoregressive language modeling using three to five research papers | 54 |
| `dd4daed7-029f-4e29-b246-e5e6903154e6` | Compare Longformer and Big Bird as approaches to processing long sequences | 69 |
| `4659e4d1-7071-4654-9494-3f5eefb14fc7` | Explore how large language models process and use long contexts | 73 |
| `f7fdc89b-bff5-4cb1-a565-d26b3b6097a0` | Explore how large language models process and use long contexts | 75 |

全体 36 个任务的最新评分中，35 个成功，1 个失败；失败发生在上表未配对的 Longformer/Big Bird 任务，错误为 `EVALUATION_INVALID_RESPONSE`，分数保持缺失而非补零。历史评分由清单中的 `evaluation_id` 固定；在线任务详情默认显示最新评分，未来重评可能改变它。

## 6. 适用范围与后续复现

- 每例每种模式只运行一次，未随机化顺序，没有固定并发、固定负载、冷/热缓存或外部共享负载控制；结果不支持统计显著性或因果结论。
- 全部结果为 `partial`；需要结合答案、引用覆盖和未解决问题检查实际完成程度。脱敏清单不包含完整答案、原文 PDF 或评分解释，不能仅凭清单人工复核全部语义判定。
- 5 对评分提示词版本不一致，故质量表仅用 10 对；新的重跑应统一当前 v2 评分并独立记录，不与旧版本混合。没有执行历史重新评分来改变本报告数据。
- 3 对综述论文输入顺序不同；领域调研的动态语料未冻结。指定版本 PDF 若重新下载后 SHA-256 不同，应标记数据变化。
- 当前配置启用某能力不等于 trace 实际执行了它。没有检索和 Reflection 调用，不能报告它们的实测贡献。
- GPU 是共享设备采样，模型服务原始启动配置未完整归档；本报告不是 `server/` 与 `server-opt/` 的服务优化对照实验。
- 后续实验应记录完整软件/模型/服务配置，增加交替顺序的多轮配对，统一评分版本，并把研究完成状态、缺失指标、端到端耗时和 Agent 耗时分别报告。

数值来自快照的离线汇总，本次文档整理没有提交新研究或调用评分模型。具体重跑命令与指标字段见[根 README](../README.md#evaluation)。
