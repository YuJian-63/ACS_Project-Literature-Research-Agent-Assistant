import { Button } from 'antd';
import { useLocale } from '../../i18n';
import type { DimensionKey, EvaluationStatus, TaskMetrics } from '../../api/taskMetrics';
import type { EvaluationVersion } from '../../api/evaluations';
import { formatMetric as value } from '../../shared/lib/taskMetrics';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import { EvaluationData } from './EvaluationData';
import EvaluationTelemetry from './EvaluationTelemetry';
import { useEvaluation } from './useEvaluation';
import './evaluation.css';

const dimensions: [DimensionKey, string, string][] = [
  ['grounded_correctness', '事实与证据一致性', 'Grounded correctness'], ['citation_support', '引用支持程度', 'Citation support'],
  ['task_completion', '任务完成度', 'Task completion'], ['analysis_quality', '分析质量', 'Analysis quality'], ['clarity', '表达清晰度', 'Clarity'],
];
const statuses: Record<EvaluationStatus, [string, string]> = {
  not_requested: ['尚未评分', 'Not requested'], pending: ['等待评分', 'Pending'], running: ['正在评分', 'Running'],
  succeeded: ['评分完成', 'Succeeded'], failed: ['评分失败', 'Failed'], skipped: ['已跳过评分', 'Skipped'],
};
export default function EvaluationPanel({ metrics, taskId, onRequested }: { metrics?: TaskMetrics; taskId?: string; onRequested?: () => void }) {
  const locale = useLocale();
  const c = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  const detail = useEvaluation(taskId, metrics?.evaluation, onRequested);
  const evaluation = metrics?.evaluation;
  const pending = evaluation?.status === 'pending' || evaluation?.status === 'running';
  const canRequest = Boolean(taskId && onRequested && evaluation?.configured && !pending && evaluation.status !== 'succeeded'
    && !(detail.version?.max_attempts != null && detail.version.attempts >= detail.version.max_attempts));
  return <>
    {evaluation && <div className="evaluation-actions"><p>{evaluation.configured ? c('评分由独立模型异步完成，不影响研究正文。', 'Independent asynchronous evaluation does not alter your research.') : c('评分未启用或未配置。历史评分与执行指标仍可查看。', 'Evaluation is disabled or unconfigured. Historical scores and execution metrics remain available.')}</p>
      {canRequest && <Button onClick={() => void detail.request()} loading={detail.busy} disabled={detail.busy}>{evaluation.status === 'failed' || evaluation.status === 'skipped' ? c('重试评分', 'Retry evaluation') : c('申请评分', 'Request evaluation')}</Button>}
    </div>}
    {detail.submitError && <ErrorNotice error={detail.submitError} title={c('评分申请未成功', 'Evaluation request failed')} />}
    {detail.error && <ErrorNotice error={detail.error} retry={detail.reload} title={c('完整报告读取失败', 'Could not load the full report')} />}
    {detail.loading && <p className="evaluation-caption" role="status">{c('正在读取完整评估报告…', 'Loading the full evaluation report…')}</p>}
    <EvaluationReportView metrics={metrics} version={detail.version} />
  </>;
}

export function EvaluationReportView({ metrics, version }: { metrics?: TaskMetrics; version?: EvaluationVersion }) {
  const locale = useLocale();
  const c = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  if (!metrics) return <section className="evaluation-panel"><p role="status">{c('当前服务未提供指标', 'This service has not provided metrics')}</p></section>;
  const evaluation = metrics.evaluation;
  const scored = evaluation.status === 'succeeded' && evaluation.assessment === 'scored';
  const report = version?.status === 'succeeded' ? version.report : null;
  const scope = report?.evaluation_scope;
  return <section className="evaluation-panel evaluation-report" aria-label={c('研究评估报告', 'Research evaluation report')}>
    <header className="evaluation-report-header"><div><span className="research-section-label">EVALUATION REPORT</span><h2>{c('一份有依据的研究评估', 'An evidence-based research assessment')}</h2><p className="evaluation-caption">{evaluation.provider || '—'} · {evaluation.model || '—'} · {evaluation.rubric_version || '—'}</p></div><span className="evaluation-status-badge" role="status">{c(...statuses[evaluation.status])}</span></header>
    <div className="evaluation-report-overview"><aside className="evaluation-total"><span>{c('综合评分', 'Overall score')}</span><div className="evaluation-total-number">{value(scored ? evaluation.overall_score : null)} <small>/ {evaluation.overall_score_max}</small></div><p className="evaluation-caption">{c('直接采用后端加权结果', 'Weighted result from the backend')}</p>
      <p className="evaluation-scope">{scope === 'original_pages' ? c('评估范围：部分原文引用页', 'Scope: some original cited pages') : scope === 'evidence_only' ? c('评估范围：返回的证据摘录', 'Scope: returned evidence excerpts') : c('评估范围：尚未提供', 'Scope: not yet reported')}</p><p className="evaluation-caption">{c('独立模型评审结果，仅供核对参考。', 'Independent model assessment for review and verification.')}</p>
      {evaluation.assessment === 'insufficient_evidence' && <p className="evaluation-status-note">{c('证据不足，无法可靠评分；不代表零分。', 'Insufficient evidence to score reliably; this is not a zero score.')}</p>}
      {(evaluation.status === 'pending' || evaluation.status === 'running') && <p className="evaluation-status-note">{c('评分进行中，完成后自动更新。', 'Evaluation is in progress and will refresh automatically.')}</p>}
      {evaluation.error_code && <p className="evaluation-status-note">{evaluation.error_code}</p>}
    </aside><div className="evaluation-dimensions"><h3>{c('五维质量评估', 'Five quality dimensions')}</h3>{dimensions.map(([key, zh, en]) => {
      const dimension = evaluation.dimensions[key];
      const score = scored ? dimension.score : null;
      return <article className="evaluation-dimension" key={key}><div className="evaluation-dimension-heading"><h4>{c(zh, en)} <small>{c('权重', 'Weight')} {value(evaluation.weights[key], '%')}</small></h4><span>{value(score)} / {evaluation.score_max}</span></div>
        {score != null && <div className="evaluation-meter" role="meter" aria-label={c(zh, en)} aria-valuenow={score} aria-valuemin={0} aria-valuemax={evaluation.score_max}><span style={{ width: `${evaluation.score_max > 0 ? Math.max(0, Math.min(100, score / evaluation.score_max * 100)) : 0}%` }} /></div>}
        <p>{dimension.reason || c('暂无评分说明', 'No assessment reason available')}</p></article>;
    })}</div></div>
    <section className="evaluation-report-section"><header><span className="research-section-label">REVIEW FINDINGS</span><h3>{c('评审结论与改进建议', 'Findings and recommendations')}</h3></header>
      {report ? <><p className="evaluation-summary">{report.summary || '—'}</p><h4>{c('需要关注的问题', 'Issues to review')} · {report.issues?.length ?? 0}</h4>{report.issues?.length ? report.issues.map((issue, index) => <article className="evaluation-issue" key={index}><span className="evaluation-issue-index">{String(index + 1).padStart(2, '0')}</span><div><div className="evaluation-issue-meta">{issue.severity} · {issue.code}</div><p>{issue.message}</p>{issue.answer_excerpt && <blockquote>{issue.answer_excerpt}</blockquote>}<p className="evaluation-caption">{c('关联引用', 'Related citations')}: {issue.citation_keys?.join(' · ') || '—'}</p></div></article>) : <p className="evaluation-empty">{c('未报告问题', 'No issues reported')}</p>}
      <h4>{c('改进建议', 'Suggestions')}</h4>{report.suggestions?.length ? <ol className="evaluation-suggestions">{report.suggestions.map((suggestion, index) => <li key={index}>{suggestion}</li>)}</ol> : <p className="evaluation-empty">—</p>}
      <h4>{c('证据范围与限制', 'Evidence scope and limitations')}</h4><EvaluationData value={report.limitations} />
      <details className="evaluation-disclosure"><summary>{c('证据核查与引用检查', 'Evidence and reference checks')}</summary><EvaluationData value={{ evidence_checks: report.evidence_checks, reference_checks: report.reference_checks }} /></details>
      </> : <p className="evaluation-empty">{c('暂无完整报告。已有评分摘要和执行指标仍可在本页查看。', 'No full report yet. Available summary scores and execution metrics remain visible.')}</p>}
    </section>
    <EvaluationTelemetry metrics={metrics} />
    <section className="evaluation-report-section"><header><span className="research-section-label">AUDIT & METADATA</span><h3>{c('版本与完整返回数据', 'Version and complete response data')}</h3></header><p className="evaluation-caption">{c('包含状态、配置标记、权重、版本、尝试次数、时间、摘要、用量与所有附加字段。', 'Includes states, configuration flags, weights, versions, attempts, timestamps, digests, usage and all additional fields.')}</p>
      <details className="evaluation-disclosure"><summary>{c('全部任务指标', 'All task metrics')} · {metrics.schema_version}</summary><EvaluationData value={metrics} /></details>
      <details className="evaluation-disclosure"><summary>{c('完整评估响应与独立评分模型用量', 'Full evaluation response and independent judge usage')}</summary><EvaluationData value={version} /></details>
    </section>
  </section>;
}
