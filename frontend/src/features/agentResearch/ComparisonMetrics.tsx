import type { AgentResearchRecord } from '../../api/agentResearch';
import type { DimensionKey, EvaluationMetrics } from '../../api/taskMetrics';
import { useLocale } from '../../i18n';
import { StatusBadge } from '../../shared/components/StatusBadge';
import { formatMetric } from '../../shared/lib/taskMetrics';
import { compatibleScores, scoreDifference } from './lib/reportComparison';

const dimensions: [DimensionKey, string, string][] = [
  ['grounded_correctness', '事实与证据一致性', 'Grounded correctness'], ['citation_support', '引用支持程度', 'Citation support'],
  ['task_completion', '任务完成度', 'Task completion'], ['analysis_quality', '分析质量', 'Analysis quality'], ['clarity', '表达清晰度', 'Clarity'],
];
export function ComparisonMetrics({ records, comparableInputs }: { records: [AgentResearchRecord, AgentResearchRecord]; comparableInputs: boolean }) {
  const locale = useLocale();
  const c = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  const evaluation = records.map(record => record.metrics?.evaluation);
  const canDiff = compatibleScores(evaluation[0], evaluation[1]);
  function evaluationLabel(e?: EvaluationMetrics) {
    if (!e) return c('未提供', 'Not provided');
    if (e.status === 'succeeded' && e.assessment === 'insufficient_evidence') return c('证据不足，无法评分', 'Insufficient evidence');
    return ({ not_requested: c('尚未评分', 'Not requested'), pending: c('等待评分', 'Pending'), running: c('正在评分', 'Evaluating'), succeeded: c('评分完成', 'Scored'), failed: c('评分失败', 'Failed'), skipped: c('已跳过评分', 'Skipped') })[e.status];
  }
  function scored(e?: EvaluationMetrics) { return e?.status === 'succeeded' && e.assessment === 'scored'; }
  function difference(a: number | null | undefined, b: number | null | undefined, enabled = true) {
    if (!enabled || a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b)) return '—';
    const value = Number((b - a).toFixed(2));
    return `${value > 0 ? '+' : ''}${value}`;
  }
  const table = (full: boolean) => <table className="comparison-metrics-table"><caption className="comparison-visually-hidden">{c('两份报告的评分和执行指标', 'Scores and execution metrics for both reports')}</caption><thead><tr><th scope="col">{c('指标', 'Metric')}</th><th scope="col">{c('报告 A', 'Report A')}</th><th scope="col">{c('报告 B', 'Report B')}</th><th scope="col">B − A</th></tr></thead><tbody>
    {!full && <><tr><th scope="row">{c('任务状态', 'Task status')}</th>{records.map(record => <td key={record.task_id}><StatusBadge status={record.status} /></td>)}<td>—</td></tr>
    <tr><th scope="row">{c('评分状态', 'Evaluation status')}</th>{evaluation.map((e, i) => <td key={i}>{evaluationLabel(e)}</td>)}<td>—</td></tr>
    <tr className="comparison-total-row"><th scope="row">{c('综合评分', 'Overall score')}</th>{evaluation.map((e, i) => <td key={i}>{scored(e) && e?.overall_score != null ? `${formatMetric(e.overall_score)} / ${formatMetric(e.overall_score_max)}` : '—'}</td>)}<td>{canDiff ? difference(0, scoreDifference(evaluation[0], evaluation[1]), true) : '—'}</td></tr></>}
    {full && dimensions.map(([key, zh, en]) => <tr key={key}><th scope="row">{c(zh, en)}</th>{evaluation.map((e, i) => <td key={i}>{scored(e) && e?.dimensions[key]?.score != null ? `${formatMetric(e.dimensions[key].score)} / ${formatMetric(e.score_max)}` : '—'}</td>)}<td>{difference(evaluation[0]?.dimensions[key]?.score, evaluation[1]?.dimensions[key]?.score, canDiff)}</td></tr>)}
    {!full && <><tr><th scope="row">{c('耗时（秒）', 'Elapsed time (s)')}</th>{records.map(record => <td key={record.task_id}>{formatMetric(record.result?.usage.elapsed_seconds)}</td>)}<td>{difference(records[0].result?.usage.elapsed_seconds, records[1].result?.usage.elapsed_seconds)}</td></tr>
    <tr><th scope="row">{c('Token 用量', 'Token usage')}</th>{records.map(record => <td key={record.task_id}>{formatMetric(record.result?.usage.total_tokens)}{record.result?.usage.token_usage_complete === false && <small> {c('不完整', 'Incomplete')}</small>}</td>)}<td>{difference(records[0].result?.usage.total_tokens, records[1].result?.usage.total_tokens, records.every(record => record.result?.usage.token_usage_complete === true))}</td></tr></>}
  </tbody></table>;
  return <section className="comparison-overview"><h2>{c('评测概览', 'Evaluation overview')}</h2>{table(false)}
    <details><summary>{c('展开五维评分', 'Show five quality dimensions')}</summary>{table(true)}</details>
    {!canDiff && <p className="comparison-note">{c('评分缺失或评分模型、规则、尺度不一致时不计算分差；缺失值不代表零分。', 'Score deltas require compatible scored evaluations, including matching judge, rubric and scale. Missing values are not zero.')}</p>}
    {!comparableInputs && <p className="comparison-note">{c('问题或预选论文不同、或预选论文信息缺失；差值仅作数值参考，不能据此判断方法优劣。', 'Questions or selected papers differ, or selected paper information is missing. Numerical deltas do not establish method quality.')}</p>}
    <p className="comparison-note">{c('差值为 B − A，仅作数值参考，不自动判断哪种方法更好。', 'Deltas are B − A and do not establish which method is better.')}</p>
  </section>;
}
