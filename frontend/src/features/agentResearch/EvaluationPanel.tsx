import { useLocale } from '../../i18n';
import type { DimensionKey, EvaluationStatus, TaskMetrics } from '../../api/taskMetrics';
import { formatMetric } from '../../shared/lib/taskMetrics';

const dimensions: [DimensionKey, string, string][] = [
  ['grounded_correctness', '事实与证据一致性', 'Grounded correctness'],
  ['citation_support', '引用支持程度', 'Citation support'],
  ['task_completion', '任务完成度', 'Task completion'],
  ['analysis_quality', '分析质量', 'Analysis quality'],
  ['clarity', '表达清晰度', 'Clarity'],
];
const statuses: Record<EvaluationStatus, [string, string]> = {
  not_requested: ['尚未评分', 'Not requested'], pending: ['等待评分', 'Pending'],
  running: ['正在评分', 'Running'], succeeded: ['评分完成', 'Succeeded'],
  failed: ['评分失败', 'Failed'], skipped: ['已跳过评分', 'Skipped'],
};

export default function EvaluationPanel({ metrics }: { metrics?: TaskMetrics }) {
  const locale = useLocale();
  const copy = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  if (!metrics) return <section className="evaluation-panel"><p role="status">{copy('当前服务未提供指标', 'This service has not provided metrics')}</p></section>;
  const { evaluation, agent, model_server: server } = metrics;
  const scored = evaluation.status === 'succeeded' && evaluation.assessment === 'scored';
  const value = formatMetric;
  return <section className="evaluation-panel" aria-label={copy('研究评估', 'Research evaluation')}>
    <header className="evaluation-heading"><span className="research-section-label">EVALUATION</span><h2>{copy('研究质量与执行指标', 'Research quality and execution metrics')}</h2></header>
    <p role="status">{copy(...statuses[evaluation.status])}{evaluation.assessment === 'insufficient_evidence' && ` · ${copy('证据不足，无法评分', 'Insufficient evidence to score')}`}{evaluation.error_code && ` · ${evaluation.error_code}`}</p>
    <div className="evaluation-section-heading"><h3>{copy('综合评分', 'Overall score')}: {value(scored ? evaluation.overall_score : null)} / {evaluation.overall_score_max}</h3><span>{evaluation.model} {evaluation.rubric_version}</span></div>
    <div className="evaluation-metrics">{dimensions.map(([key, zh, en]) => <article className="evaluation-metric" key={key}><h4>{copy(zh, en)}</h4><div className="evaluation-score">{value(scored ? evaluation.dimensions[key].score : null)} / {evaluation.score_max}</div><p>{evaluation.dimensions[key].reason || '—'}</p></article>)}</div>
    <section className="evaluation-execution"><h3>{copy('Agent 执行用量', 'Agent usage')}</h3><p>{agent.unavailable_reason}{agent.token_usage_complete === false && copy(' · Token 部分采集', ' · Partial token usage')}</p><dl>{[
      [copy('Agent 步数', 'Agent steps'), agent.agent_steps], [copy('模型调用', 'Model calls'), agent.model_calls],
      [copy('工具调用', 'Tool calls'), agent.tool_calls], [copy('输入 Token', 'Input tokens'), agent.input_tokens],
      [copy('输出 Token', 'Output tokens'), agent.output_tokens], [copy('总 Token', 'Total tokens'), agent.total_tokens],
    ].map(([label, number]) => <div key={String(label)}><dt>{label}</dt><dd>{value(number as number | null)}</dd></div>)}</dl></section>
    <section className="evaluation-serving"><h3>{copy('模型服务性能', 'Model serving performance')}</h3><p>{server.status} · {server.unavailable_reason}</p>
      <div className="evaluation-table-wrap"><table><thead><tr><th>{copy('指标', 'Metric')}</th><th>{copy('均值', 'Mean')}</th><th>{copy('样本 / 来源', 'Samples / source')}</th></tr></thead><tbody>{([
        ['TTFT', server.ttft_ms, ' ms'], ['TPOT', server.tpot_ms, ' ms/token'],
        ['Mean ITL', server.mean_itl_ms, ' ms'], [copy('生成速度', 'Generation speed'), server.tokens_per_second, ' tokens/sec'],
      ] as const).map(([label, metric, unit]) => <tr key={label}><th>{label}</th><td>{value(metric.mean, unit)}</td><td>{metric.samples} / {metric.source || metric.unavailable_reason || '—'}</td></tr>)}</tbody></table></div>
      <h3>{copy('缓存 Token', 'Cache tokens')}</h3><p>{copy('命中 / 查询', 'Hit / query')}: {value(server.cache_hit_tokens)} / {value(server.cache_query_tokens)} · {value(server.cache_hit_ratio, '%', 100)}</p>
      <p>{copy('有效请求覆盖', 'Measured requests')}: {server.cache_measured_model_calls} / {value(server.model_calls_total)} · {server.cache_usage_complete ? copy('完整采集', 'Complete') : copy('部分采集', 'Partial')} {server.cache_unavailable_reason}</p>
      <h3>{copy('GPU 最近利用率快照', 'Latest GPU utilization snapshot')}</h3><p>{copy('响应完成时的设备快照，可能包含其他进程。', 'Device snapshots at response completion may include other processes.')}</p>
      {server.gpus.length ? <ul>{server.gpus.map(gpu => <li key={gpu.uuid}>{gpu.uuid}: {value(gpu.utilization_percent, '%')} · #{gpu.call_index} · {gpu.sampled_at || '—'}</li>)}</ul> : <p>{copy('未采集', 'Not collected')}</p>}
    </section>
  </section>;
}
