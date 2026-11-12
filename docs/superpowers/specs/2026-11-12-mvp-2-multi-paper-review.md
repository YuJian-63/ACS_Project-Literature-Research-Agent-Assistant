# MVP-2：多论文综述与比较

## 目标

开放真实 Runner 的 `review` 任务。用户可基于 2—20 篇已解析论文生成有来源支持的主题综述和结构化比较表；保留现有 Mock 结果与 API 兼容性。

## 范围与非目标

- 复用现有论文上传、解析、任务队列、LangGraph 单节点、OpenAI-compatible 模型客户端、引用表和 Artifact schema；不增加数据库迁移。
- 只处理用户明确选中的 ready 论文，继续在提交时冻结论文 ID、SHA-256、模型及 Runner 配置。
- 在现有字符/Token/时间预算内做确定性的词法证据选择，并尽可能让每篇论文获得独立、非零且受限的证据配额；保留每条证据的 paper/chunk/page 身份。
- 单次模型调用生成综述正文、引用候选和比较表，不启用搜索工具、隐式重试、向量检索、OCR、反思循环或跨请求记忆。
- 保留 Mock review 的现有行为；真实 summary/qa 行为不变。
- 不包含联网搜索、自动发现论文、用户/权限、多用户配额、评测集建设或 TACC/vLLM 部署。

## 输入与检索

- `TaskCreate` 已定义 review 至少选择 2 篇、最多 20 篇且必须提供问题；服务端仅在 `TASK_RUNNER=langgraph` 且模型配置完整时创建真实 review，未 ready 论文仍返回 `PAPER_NOT_READY`。
- Worker 逐一检查每篇论文仍为 ready，且 SHA-256 与任务快照一致；任何来源改变都以既有错误码失败，不混入新论文。
- 证据检索以论文分组，在总 `evidence_context_chars` 和总 chunk 上限内均衡分配，顺序稳定、可复现。先为每篇有 chunk 的论文保留一个最短的有效 chunk，再按问题相关度 round-robin 增补片段；若所有有 chunk 的论文无法至少各保留一个片段（字符总预算或 chunk 上限不足），任务以 `BUDGET_EXCEEDED` 失败，不调用模型，不能静默偏向排序靠前的论文。
- 没有 chunk 的论文仍须出现在比较表中，模型对其内容列返回 null 且无引用。若所有选定论文都没有可用 chunk，服务端不调用模型并成功返回固定的“证据状态”单列比较表；每篇论文标为“未检索到可用解析证据”，综述正文明确说明证据不足，引用为空；input_tokens、output_tokens、model_calls、tool_calls 和 total_tokens 均精确为 0（详见 implementation decisions addendum）。

## 模型输出与校验

模型返回单个 JSON 对象：

```json
{
  "content_markdown": "综述正文，引用用 [[cite:1]] 标记",
  "citations": [{"chunk_id": "UUID", "quote": "片段原文连续子串"}],
  "comparison_table": {
    "columns": [{"key": "method", "label": "研究方法"}],
    "rows": [{
      "paper_id": "UUID",
      "cells": {"method": {"value": "方法描述或 null", "citation_indexes": [1]}}
    }]
  }
}
```

- 服务端验证表格列数、列键唯一与格式、行与已选论文集合完全相等、每行 cell 键与 columns 完全相等、value 类型及长度、citation index 唯一且存在。
- 引用 chunk 必须在本次证据上下文内；quote 必须是原文连续子串；正文或表格至少有一处引用每条 citations 项；拒绝重复引用。
- 表格中的 citation index 必须映射到同一 paper_id 的已验证引用；服务器生成 `C1…Cn`，并将表格索引转换为 `citation_keys`。模型不得指定最终引用键。
- 输出表与正文、引用、usage、成功状态和事件在同一事务内写入；校验失败使用 `INVALID_AGENT_RESULT`，不留下部分结果。
- 真实 review Artifact 的 `comparison_table` 必须非空；summary/qa 继续为 null。Mock review 保持现有模拟产物且 comparison_table 为空。

## 前端与 API

- API 请求和响应 envelope 不变，取消真实 Runner 对 review 的禁止；仍要求已配置模型及 ready 论文。
- Artifact 继续使用契约既有 `ComparisonTable` 结构；每行链接原 PDF，每个 citation key 链接到对应来源引用卡片。
- 新任务页说明执行方式由服务器配置选择，不能固定宣称一定使用 Mock 或真实模型。
- README/API 文档更新真实 review 前置条件、预算/证据行为和比较表校验规则。

## 验收重点

- 2 篇与 20 篇论文均能获得稳定的平衡证据选择；超上下文预算时总量不超限，论文顺序变化不改变选择结果。
- 同名/相似内容的 chunk 不得造成跨论文引用；错 paper、缺行、多行、错 cell、空 evidence、无效/跨论文表格引用都拒绝或按规定返回空值表。
- Mock regressions、summary/qa regressions、API/Worker integration、前端 typecheck/build 与浏览器比较表/引用交互通过。
- 不声称 live model provider 或 native PostgreSQL 已验收，除非随后实际配置并运行。
