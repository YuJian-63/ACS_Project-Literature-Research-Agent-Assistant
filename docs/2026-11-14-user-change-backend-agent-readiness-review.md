# 用户改动：后端 Agent 对接就绪审查

日期：2026-11-14；归属：user-change（用户发起，Codex 协助）。
范围：代码与 API 契约阅读、离线复现、现有 unittest 回归；未改业务代码。
本文件为新增审查记录，不替换历史设计、开发和验收记录。

## 结论

已有论文、任务、证据和产物基础设施，可开始 Agent 契约设计；不能据此宣称后端没有问题。
建议在正式结果验收前修复下面两项结果校验问题。独立 Agent 服务仍缺任务执行和结果回传协议。

## 已复现问题

### 重要：单篇结果可无引用通过

位置：research/validation.py 的 validate_selected_evidence_result → validate_paragraph_result → validate_result。
向单篇 evidence-v4 校验器提供含一个真实 EvidenceChunk 的上下文，传入：

```json
{"paragraphs":[{"content_markdown":"This method achieves 99.9% accuracy and outperforms all baselines.","evidence_ids":[]}]}
```

校验返回该肯定结论，citations 数量为 0。根因：引用列表可空，后续仅检查已有引用身份与原文，
没有将无引用的实质性答案与允许的“证据不足”响应区分。来源一致性校验也不能保证引用语义支持。
建议为证据不足建立显式结果状态，并约束实质性段落的引用；不采用仅凭某几个关键词判断的方式。

### 重要：单篇路径未拒绝异常 finish_reason

位置：workers/research.py execute 中 graph.invoke 后的校验与 complete_real 调用。
离线使用真实 LangGraph 和 Worker execute，替换任务加载、数据库写入与模型响应。
模型输出格式合法、引用 E1 正确，finish_reason 分别为 length 和 content_filter。
两次均调用了 complete_real，没有调用 fail_owned。此复现证明执行路径允许提交成功，
不声称已在 PostgreSQL 真正写入。根因：finish_reason 只在解析失败诊断中使用，没有成功前置检查。
分阶段 review_runner.py 已有对应结束原因检查；单篇路径应明确相同原则和兼容规则。

## 对接缺口与能力边界

- evidence HTTP 读取已实现；外部 Agent 任务领取、租约心跳、阶段上报、结果/失败回传尚无 HTTP 协议。
  现有任务执行主要是 RunnerWorker 内的 Python 调用；内嵌 Agent 可直接适配该边界。
- 不能通过客户端提交 runner_type 或自定义工作流；extended 返回 WORKFLOW_NOT_AVAILABLE。
- LangGraph 单篇图仅有 generate 节点，没有提案中的完整 ReAct/Planner/Reflection 工具循环。
- QA 目前按词项交集选择证据，无 pgvector/embedding 语义检索；跨语言与同义表达可能漏召回。
- 无 OCR、研究任务取消/原地重试/删除、SSE；这些属于已知范围边界，非此次发现的回归。
- 现有模型适配要求 Chat Completions JSON 输出；Qwen/vLLM 部署参数与实际响应需要真实联调。
- 无正式评测数据与效果评估流水线；仓库现有测试不能替代真实研究质量验收。

## 验证

`/private/tmp/evidence-api-venv/bin/python -m unittest discover -s backend/tests`
结果：39 项，31 通过，8 项因缺隔离 PostgreSQL 配置跳过。
临时环境采用 pyproject 允许范围安装，未按 uv.lock 锁定，不代表锁定环境复测。
没有运行真实模型、arXiv 或 PostgreSQL 验收，也没有覆盖全后端故障注入。

## 建议顺序

1. 修复并回归上述两项结果校验问题。
2. 明确 Agent 内嵌 Python 运行，还是独立 HTTP 服务；分别设计输入输出适配或执行协议。
3. 在隔离 PostgreSQL 和目标模型上做 summary/qa/review 的成功、失败及恢复联调。
4. OCR、取消、向量检索等按项目实际验收范围再排期。
