import type { AgentResearchRecord } from '../../../api/agentResearch';
import type { EvaluationMetrics } from '../../../api/taskMetrics';
import { isPaperId } from './researchSource';

export function comparisonIds(parameters: URLSearchParams): [string, string] | null {
  const a = parameters.get('a')?.toLowerCase(), b = parameters.get('b')?.toLowerCase();
  return a && b && isPaperId(a) && isPaperId(b) && a !== b ? [a, b] : null;
}
export function matchingInputs(a: Pick<AgentResearchRecord, 'question' | 'paper_ids'>, b: Pick<AgentResearchRecord, 'question' | 'paper_ids'>) {
  const normalize = (s: string) => s.trim().replace(/\s+/g, ' ');
  const papers = (ids: string[]) => [...new Set(ids.map(id => id.toLowerCase()))].sort().join(',');
  return { question: Boolean(normalize(a.question)) && normalize(a.question) === normalize(b.question),
    papers: !a.paper_ids.length || !b.paper_ids.length ? null : papers(a.paper_ids) === papers(b.paper_ids) };
}
export function compatibleScores(a?: EvaluationMetrics, b?: EvaluationMetrics): boolean {
  if (!a || !b || a.status !== 'succeeded' || b.status !== 'succeeded' || a.assessment !== 'scored' || b.assessment !== 'scored') return false;
  const same = ['provider', 'model', 'rubric_version', 'prompt_version', 'score_max', 'overall_score_max'] as const;
  if (!same.every(key => a[key] != null && a[key] !== '' && a[key] === b[key])) return false;
  const weights = (value: Record<string, number>) => JSON.stringify(Object.entries(value).sort(([x], [y]) => x.localeCompare(y)));
  return a.score_max > 0 && a.overall_score_max > 0 && weights(a.weights) === weights(b.weights);
}
export function scoreDifference(a?: EvaluationMetrics, b?: EvaluationMetrics): number | null {
  if (!compatibleScores(a, b) || a?.overall_score == null || b?.overall_score == null || !Number.isFinite(a.overall_score) || !Number.isFinite(b.overall_score)) return null;
  return Number((b.overall_score - a.overall_score).toFixed(2));
}

export function reportedConfig(record: AgentResearchRecord): Record<string, unknown> {
  const config = record.result?.configuration ?? {};
  const task = config.task;
  const search = task && typeof task === 'object' && !Array.isArray(task) ? (task as Record<string, unknown>).allow_search : undefined;
  return { ...config, allow_search: config.allow_search ?? (typeof search === 'boolean' ? search : undefined) };
}
