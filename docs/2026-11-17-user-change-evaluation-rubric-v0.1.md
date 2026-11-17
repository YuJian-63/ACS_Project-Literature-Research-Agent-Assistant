# 用户改动：研究任务评价标准 v0.1

日期：2026-11-17；user-change；初版建议，供小组确认和后续强化。
版本：evaluation-rubric-v0.1。本文件不是已执行的评测结果。
依据：Proposal.md第3节、agent/agent-io-interface-v1.md、当前后端保存的Agent输入/结果/trace。

## 1. 定位

评估单个研究任务：输入要求、最终答案/比较表、引用原文、运行trace及统计。
DeepSeek充当辅助评审；不自动将其意见等同于标注集真实准确率。
规则检查与模型评审分别记录。业务任务succeeded/failed不由评价改写。
摘要、问答、综述与混合任务均适用，以question的实际要求为准，task_type仅作提示。

## 2. 六项质量维度

每项为0—4整数，另有insufficient_information（信息不足）和not_applicable（不适用）。
信息不足时score=null，不能按0分或满分计算。每项都须给出理由和具体输入/输出/证据定位。

| 维度 | 权重 | 检查内容 | 0分 | 2分 | 4分 |
| --- | --- | --- | --- | --- | --- |
| task_alignment 任务契合 | 15 | 是否回应问题及格式/范围要求 | 答非所问 | 核心问题部分回应，遗漏明确要求 | 实质性要求均回应，证据缺口明确说明 |
| factual_grounding 事实依据 | 25 | 给出的具体结论是否被提供原文支持，有无猜测和条件错误 | 存在核心结论与证据明显矛盾 | 部分结论有依据，但存在重要无依据推断 | 可核查的实质性结论均有直接支持，正确保留适用条件 |
| citation_quality 引用质量 | 20 | 引用标识、位置、覆盖到对应主张及语义支持 | 引用普遍无效或核心结论引用相反证据 | 多数引用存在，但关键主张支持不足或指向模糊 | 所评估主张引用明确、可追溯，原文支持对应结论 |
| coverage 要点覆盖 | 15 | 对明确任务要点/提供参考事实的覆盖 | 已知关键要点几乎全缺失 | 覆盖部分关键要点但遗漏重要部分 | 对给定明确要点充分覆盖，未报告内容不编造 |
| comparison_quality 比较质量 | 15 | 综述/混合比较任务是否按一致维度对齐，区分条件差异 | 比较对象/指标混淆，出现核心错误排名 | 有共同维度，但条件差异和缺失信息处理不全 | 维度对应、依据充分，条件不可比和未报告明确标注 |
| process_quality 执行过程 | 10 | trace中的工具选择、来源范围、错误恢复和停止是否合理 | 明确违反来源限制或反复无效操作且无处理 | 工具大体相关，但有可避免重复或覆盖缺口未处理 | 操作与任务一致，复用已读资料，合理恢复并解释停止 |

1分：介于0和2，存在严重缺陷但有少量有效内容；3分：介于2和4，主体可靠但有局部问题。
不能仅因调用次数少、耗时短、答案长或trace长给高分；过程依据是有效性与遵守约束。

### 信息不足与不适用

- 没有人工参考事实且输入问题没有明确要点时，不评价“全文关键事实覆盖率”；coverage可为信息不足。
- 无参考答案但有引用原文时，factual_grounding只评价提供证据范围内的支持，不证明外部世界真实准确率。
- 没有比较要求时，comparison_quality不适用。不能仅因task_type=review就忽视实际question。
- 缺失trace时，process_quality信息不足；trace合法但无工具调用且任务本可直接回答，不自动扣分。
- 无原文且有实质性研究结论时，记录unsupported_claim；没有原文不能凭空推断结论正确或错误。
- “证据不足”回答应评价是否诚实、合理；不能等同成功回答了问题，也不能自动在所有维度判0。
- 执行失败但保留部分输出时仍可分析过程和可核查内容；execution_status与质量分开。

## 3. 总分规则（暂定）

适用维度中只要有信息不足项，overall_score=null，返回可评维度权重占比assessment_coverage。
全部适用维度均可评时：overall_score=round(100×Σ(weight×score/4)/Σ(applicable_weight),1)。
not_applicable不进入分母；权重如何排除、维度适用性和评分依据必须留存。
all-not-applicable属于无效报告，不输出总分。不设置自动“合格/不合格”阈值，待人工校准。
不同任务适用维度或证据范围不同，总分不可直接作为统一排行榜。

## 4. 与提案指标的关系

| 提案指标 | v0.1处理 |
| --- | --- |
| Key-Fact Coverage | 只有提供人工reference_facts时计算命中数/参考事实数；命中由评审建议并需人工抽查。无参考事实为null |
| Answer Accuracy | 优先逐项参考答案/事实对照；没有ground truth只报告evidence-grounded judgment，不标称真实准确率 |
| Comparison Accuracy | 有参考比较单元时记录正确/错误/无法判断；无参考比较仅给comparison_quality意见 |
| Citation Support Rate | 对评审拆出的claim-citation对记录supported/unsupported/uncertain，附引文及claim原文；这是LLM估计，不能伪装人工真值 |
| 完成率/耗时/Token | 从保存的stop_reason/usage提取，单任务仅记录状态和用量；完成率须在明确定义的任务集合上计算 |
| TTFT/TPOT/GPU利用率 | 当前任务trace通常不包含必要测量，不通过DeepSeek猜测，v0.1不提供 |

模型不自行声明分母或百分比；如果返回逐项判定，百分比由后端计算。
引用支持同时报告supported/unsupported/uncertain数量；不把uncertain静默排除形成偏高支持率。
v0.1优先提供逐项意见，不强求全部率指标；未实现项和无ground truth项明确为null。

## 5. 规则检查与诊断

后端确定性提取：stop_reason、未解决项、来源/引用数、主循环/模型/工具次数、已知Token和耗时。
检查正文/表格实际引用的ID是否存在于citations；未知引用、重复身份、页码异常分别记flag。
有保存的原始chunk时才可核对逐字引文和页码；Agent原文片段自身不能证明与原PDF逐字一致。
errors非空不等于最终失败；恢复成功的错误不能一律扣分。
区分事实错误、证据缺失、引用无效、覆盖不足、条件不可比、工具重复及运行中止。

## 6. 评审输出约定

每项维度：status、score、reason、evidence_refs（指向输入要求/输出段落/引用ID/trace索引）。
报告包含summary、strengths、issues、improvements、limitations、overall_score、assessment_coverage。
issues含severity=high/medium/low及定位，不允许只有“质量不好”等无依据判断。
每条issue的依据必须存在于本次评估快照，评审不得编造引用、trace步骤或外部论文事实。
先记录原始评审结果，后端校验并计算派生分数。格式失败为evaluation失败，不覆盖研究结果。

## 7. 后续强化

先按提案准备8—12个人工标注场景，用人工与模型意见校准评分及null比例。
固定rubric、提示词、模型、输入快照和采样规则后再比较baseline与extended。
以后新增版本文件，不原地覆盖已用于评分的版本；支持复评并保留各次报告。

## 8. 草案复核补充

assessment_coverage=可评分的适用维度权重之和/全部适用维度权重之和，范围0—1；
not_applicable排除，insufficient_information仍在分母。
v0.1的Citation Support Rate先保留null，只记录逐项意见及supported/unsupported/uncertain数量，
待小组定义并校准claim-citation对的完整枚举规则后再启用百分比。
每份合法报告必须恰好包含六个维度，不允许重复或省略；维度不适用也要显式返回状态。
