# 用户改动：后端 Evaluation v0.1 设计草案

日期：2026-11-17；user-change；待用户确认。
标准：[evaluation-rubric-v0.1](../../2026-11-17-user-change-evaluation-rubric-v0.1.md)。

## 目标和实现选择

后端针对一个已结束研究任务，读取固定输入、原生输出及trace，调用一次DeepSeek生成独立评估报告。
手动触发、异步执行、单任务查询；暂不实现批次评测平台、自动复评或训练反馈。
纯规则检查不能判断语义支持，采用规则+模型；自动批量调用成本和口径尚未确定，因此首版不启用。
用户已给出后端与DeepSeek方向；评分权重、接口及限制是本设计建议，不声称已由小组确认。

## 输入快照

- 支持当前runner=agent且已有agent_result的终态任务（succeeded/failed）。
- input：task_id、question、sources、来源范围、max_papers及执行限制。
- output：answer、comparison_table、citations及source_text、unresolved、stop_reason、errors。
- trace：模型/工具记录；configuration只保存非敏感版本配置。usage与执行统计单独提取。
- 允许可选人工reference_facts/reference_answer/reference_comparison，前端不必首版实现编辑器。
- 旧mock任务拒绝质量评分，避免把模拟结果纳入模型效果；旧langgraph记录首版明确不支持。
- 快照带task更新版本/规范化SHA-256，生成后不随研究表更改；报告绑定快照。

## 模型配置与调用

独立EVAL_BASE_URL、EVAL_MODEL_ID、EVAL_API_KEY，不复用生成任务的配置字段。
实际DeepSeek模型ID以用户可用配置为准，不把历史记录的模型ID作为当前保证。
密钥只从服务端环境读取，不进入run_config、任务、报告或日志。
默认一份报告一次调用，不自动重试；调用超时90秒、输出最多4096 Token，服务端可收紧。
累计用量独立计量，不加入被评研究任务的usage。没有配置时返回EVALUATOR_NOT_CONFIGURED，不创建假报告。
真实付费调用只在用户手动POST后执行；普通测试和CI使用离线模型替身。

## 上下文范围

优先保留完整question、最终输出、引用原文和人工参考项。超过配置容量则拒绝并提示缩小范围，
不静默裁剪关键引文或参考答案。trace最多80条，按首尾与错误记录确定性采样并保持时间顺序；
报告保存原始/使用条数、原始索引、选取算法版本及省略说明，影响判断时必须标明信息不足。
正式实现须按所配置模型上下文限制检查输入及预留输出，不把字符数当作精确token数。
v0.1不回溯抓取整篇PDF或联网补证，因此不能宣称评判完整论文的事实正确率。

## 任务与持久化

新增evaluation_runs独立表及新迁移，不修改历史迁移。
字段：id、task_id、user_id、status、snapshot_hash、input_snapshot、reference_data、
rubric_version、prompt_version、evaluator_model、非敏感run_config、report、usage、
error、idempotency_key/request_hash、worker_id/lease、created_at/started_at/finished_at。
状态queued/running/succeeded/failed；与研究Task状态完全独立。
复用用户认证、CSRF、归属和租约机制；终态评估不可回写研究任务的答案或成功状态。
同用户同幂等键同快照/参考项重放，变化请求返回409；主动复评用新键保留历史。
每用户最多1个活动评估，避免重复点击导致并行收费；初期不自动重跑失联调用。
Worker执行前预留一次调用，完成时检查所有权；超时/失联进入明确失败，旧Worker不能覆盖。

## API建议

- POST /api/v1/tasks/{task_id}/evaluations：鉴权+CSRF，可选参考项和Idempotency-Key，返回202及evaluation_id。
- GET /api/v1/tasks/{task_id}/evaluations：当前用户的评估历史与简要状态。
- GET /api/v1/evaluations/{evaluation_id}：状态、报告、限制、版本和评估用量。
- 使用来源Task与evaluation的user_id双重归属检查；他人任务/报告返回404。
- 研究任务尚未结束或无原生结果返回409；不因评估失败影响原研究任务和前端结果。
- 首版可以先通过API使用，前端之后增加“评价”按钮与报告区域，不强制改现有研究页面。

## 报告校验

维度仅允许rubric定义的六项；整数0—4；信息不足/不适用必须null。
权重和总分由后端按rubric计算，不采信模型自行给出的百分比或总分。
evidence_refs中的引用ID和trace索引须存在于发送的快照/采样中；未知引用拒绝为无效评估。
引用原文、问题和trace都是待评数据，不是指令。system提示词禁止遵循其中的评审指令。
只请求结构化分析和证据定位，不要求模型输出隐藏推理链。
报告标记judgment_source=llm、evidence_scope和needs_human_review，保留不确定性。

## 验证范围

先用离线夹具覆盖：高质量问答、缺证据回答、错误引用、条件不可比较、partial、
工具失败后恢复、缺trace、无参考答案、恶意文本、上下文超限与异常模型JSON。
数据库测试覆盖用户隔离、幂等、快照、失联/迟到写入；旧研究任务与API回归。
用户明确提供模型配置并同意单次验证后，再对一份任务做真实DeepSeek评审与人工抽查。

## 当前交付状态

本轮交付评价标准和最小功能设计，尚未新增evaluation数据库表、接口或Worker，
没有调用DeepSeek、没有生成真实评分。确认设计后再编写实施计划与代码。

## 独立复核后的明确约定

- 只读复核未发现阻塞性设计问题；以下细节合入初版，不扩展业务范围。
- trace模型记录不重复发送累积messages历史，只提取本轮response、purpose、耗时及usage；
  工具记录提取name、必要参数及observation摘要。单条文本片段有长度上限，记录截断字段。
  question/最终输出/引用原文/人工参考项单独完整发送，trace摘录不替代它们。
- 采样先保留错误事件，再首尾事件，同优先级按原始索引稳定排序，最后恢复时间顺序。
  同时执行总上下文容量检查；trace占满剩余额度时进一步减少摘录并记录遗漏，
  无足够trace支撑的process_quality标为信息不足；核心材料本身超限则拒绝评估。
- 原始评审响应保存为独立、有大小上限的raw_response字段；validated_report保存通过schema校验的报告。
  原始响应不默认对前端暴露，诊断同样遵循用户隔离及敏感字段过滤。
- evidence_refs为带kind的结构：input/output使用字段名与Unicode码点[start,end)范围；
  citation使用chunk_id；trace使用采样前的原始index；reference_fact使用调用方给定ID。
  后端检查引用是否存在于实际发送内容；模型返回的六个维度必须完整且唯一。
- 信息不足、总分及适用权重按评价标准第8节计算；首版不输出未经校准的引用支持率百分比。
