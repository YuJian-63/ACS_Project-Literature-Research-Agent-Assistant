import type { EvaluationStatus } from '../../api/taskMetrics';

export function shouldPollResearch(record: { status: string; metrics?: { evaluation: { status: EvaluationStatus } } }): boolean {
  return record.status === 'queued' || record.status === 'running'
    || record.metrics?.evaluation.status === 'pending' || record.metrics?.evaluation.status === 'running';
}

export function formatMetric(value: number | null | undefined, unit = '', multiplier = 1): string {
  return value == null ? '—' : `${Number((value * multiplier).toFixed(2))}${unit}`;
}
