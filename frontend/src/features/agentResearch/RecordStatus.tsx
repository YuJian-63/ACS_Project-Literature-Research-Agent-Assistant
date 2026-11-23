import { useCallback } from 'react';
import { Button } from 'antd';
import { Link } from 'react-router-dom';
import { agentResearch, type AgentResearchRecord, type AgentResearchSummary } from '../../api/agentResearch';
import type { EvaluationMetrics } from '../../api/taskMetrics';
import type { TaskStatus } from '../../api/types';
import { useLocale } from '../../i18n';
import { StatusBadge } from '../../shared/components/StatusBadge';
import { useResource } from '../../shared/hooks/useResource';
import { formatMetric } from '../../shared/lib/taskMetrics';

const isEvaluating = (record: AgentResearchRecord) => record.metrics?.evaluation.status === 'pending' || record.metrics?.evaluation.status === 'running';

export function RecordStatusView({ status, evaluation, error = false, taskId }: { status: TaskStatus; evaluation?: EvaluationMetrics; error?: boolean; taskId?: string }) {
  const locale = useLocale();
  const c = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  const labels = {
    not_requested: c('尚未评分', 'Not requested'), pending: c('等待评分', 'Pending evaluation'),
    running: c('正在评分', 'Evaluating'), succeeded: c('评分完成', 'Evaluation complete'),
    failed: c('评分失败', 'Evaluation failed'), skipped: c('已跳过评分', 'Evaluation skipped'),
  };
  const insufficient = evaluation?.status === 'succeeded' && evaluation.assessment === 'insufficient_evidence';
  const badgeStatus = error ? 'failed' : insufficient ? 'partial'
    : evaluation?.status === 'pending' ? 'queued'
    : evaluation?.status === 'not_requested' || evaluation?.status === 'skipped' ? 'neutral'
    : evaluation?.status || 'neutral';
  const label = error ? c('评分状态读取失败', 'Could not load evaluation') : !evaluation ? c('正在读取评分…', 'Loading evaluation…') : insufficient ? c('证据不足，无法评分', 'Insufficient evidence to score') : labels[evaluation.status];
  const score = evaluation?.overall_score;
  const scoreTone = score == null ? 'unknown' : score >= 80 ? 'high' : score >= 60 ? 'medium' : 'low';
  const scoreClass = `status-badge record-evaluation-score record-score-${scoreTone}`;
  const scoreText = <>{formatMetric(score)} / {formatMetric(evaluation?.overall_score_max)}</>;
  const evaluationUrl = taskId ? `/tasks/${encodeURIComponent(taskId)}?tab=evaluation` : undefined;
  const badge = <><span aria-hidden="true" className="status-dot" />{label}</>;
  return <div className="record-status"><StatusBadge status={status} />
    {status === 'succeeded' && <div className="record-evaluation" role="status" data-status={error ? 'unavailable' : insufficient ? 'insufficient' : evaluation?.status}>
      {taskId ? <Link className={`status-badge status-${badgeStatus}`} to={evaluationUrl!}>{badge}</Link>
        : <span className={`status-badge status-${badgeStatus}`}>{badge}</span>}
      {!error && evaluation?.status === 'succeeded' && evaluation.assessment === 'scored' && <>{evaluationUrl ? <Link className={scoreClass} to={evaluationUrl}>{scoreText}</Link> : <span className={scoreClass}>{scoreText}</span>}</>}
    </div>}
  </div>;
}

function CompletedStatus({ task }: { task: AgentResearchSummary }) {
  const taskId = task.id;
  const locale = useLocale();
  const load = useCallback((signal: AbortSignal) => agentResearch.record(taskId, signal), [task, taskId]);
  const resource = useResource(load, 30_000, isEvaluating);
  return <>
    <RecordStatusView taskId={taskId} status="succeeded" evaluation={resource.data?.metrics?.evaluation} error={Boolean(resource.error) || Boolean(resource.data && !resource.data.metrics)} />
  {resource.error && <Button size="small" type="link" onClick={resource.reload}>{locale === 'en-US' ? 'Retry' : '重试'}</Button>}</>;
}

export default function RecordStatus({ task }: { task: AgentResearchSummary }) {
  return task.status === 'succeeded' ? <CompletedStatus task={task} /> : <RecordStatusView status={task.status} />;
}
