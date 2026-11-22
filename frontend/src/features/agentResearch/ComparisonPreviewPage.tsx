import { Alert } from 'antd';
import { Link } from 'react-router-dom';
import { t, useLocale } from '../../i18n';
import { PageHeader } from '../../shared/components/PageHeader';
import type { AgentResult } from '../../api/agentResearch';
import ResultContent from './ResultContent';
import MathText from '../../shared/components/MathText';

export const comparisonPreviewId = 'preview-comparison';

export default function ComparisonPreviewPage() {
  const locale = useLocale();
  const copy = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  const question = copy('【界面示例】比较演示论文 A 与演示论文 B', '[Interface preview] Compare sample papers A and B');
  const result: AgentResult = {
    task_id: comparisonPreviewId,
    question,
    answer: '',
    comparison_table: copy(
      '| 比较维度 | 演示论文 A | 演示论文 B |\n| --- | --- | --- |\n| 研究目标 | 设计一种面向短文档的检索流程 | 探索长文档的分段分析流程 |\n| 核心方法 | 对全文建立单层索引，按问题返回相关片段 | 先识别章节，再按章节选择证据片段 |\n| 演示公式 | 行内公式 \\(s_i=q^T x_i\\) | 行内公式 \\(s_j=\\sum_k w_k x_{jk}\\) |\n| 适用场景 | 文档较短、结构简单时便于快速定位 | 文档较长、主题分散时便于逐段核查 |\n| 已知限制 | 可能遗漏跨章节关联 | 需要额外的章节识别步骤 |',
      '| Dimension | Sample paper A | Sample paper B |\n| --- | --- | --- |\n| Research goal | Design retrieval for short documents | Explore section-based analysis for long documents |\n| Core method | Index the full text and retrieve relevant passages | Identify sections, then select evidence from each section |\n| Sample formula | Inline \\(s_i=q^T x_i\\) | Inline \\(s_j=\\sum_k w_k x_{jk}\\) |\n| Best suited to | Short documents with simple structure | Long documents with dispersed topics |\n| Limitation | May miss links across sections | Requires an extra section-detection step |'
    ),
    citations: [], sources: [], unresolved: [], stop_reason: 'completed', trace: [], errors: [],
    usage: { agent_steps: 0, model_calls: 0, tool_calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, token_usage_complete: true, elapsed_seconds: 0 },
    configuration: { workflow: 'baseline', model: copy('界面示例', 'Preview') },
  };
  return <><Link className="back-link" to="/tasks">{t('返回任务列表')}</Link>
    <PageHeader title={t('研究结果')} description={t('围绕你的问题，阅读研究内容并核对原文依据。')} />
    <Alert type="info" showIcon className="inline-alert" title={copy('论文比较界面示例', 'Comparison interface preview')} description={copy('示例论文和结论均为虚构内容；未运行研究，也未保存到数据库。', 'The sample papers and claims are fictional. No research was run or saved to the database.')} />
    <div className="result-question"><span>{t('研究问题')}</span><MathText>{question}</MathText></div>
    <ResultContent result={result} />
  </>;
}
