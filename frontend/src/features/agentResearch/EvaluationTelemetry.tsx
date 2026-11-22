import { useLocale } from '../../i18n';
import type { TaskMetrics } from '../../api/taskMetrics';
import { formatMetric as value } from '../../shared/lib/taskMetrics';

export default function EvaluationTelemetry({ metrics }: { metrics: TaskMetrics }) {
  const locale = useLocale();
  const c = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  const { agent, model_server: server } = metrics;
  const usage: [string, number | null][] = [[c('Agent 步数', 'Agent steps'), agent.agent_steps], [c('模型调用次数', 'Model calls'), agent.model_calls], [c('工具调用次数', 'Tool calls'), agent.tool_calls], [c('输入 Token', 'Input tokens'), agent.input_tokens], [c('输出 Token', 'Output tokens'), agent.output_tokens], [c('总 Token', 'Total tokens'), agent.total_tokens]];
  return <div className="evaluation-telemetry">
    <section className="evaluation-report-section"><header><span className="research-section-label">AGENT USAGE</span><h3>{c('执行用量', 'Agent usage')}</h3></header>
      <p className="evaluation-caption">{c('步数与模型调用次数可能不同；规划、反思也可能调用模型。以下 Token 不含独立评分模型用量。', 'Steps and model calls may differ due to planning and reflection. Tokens exclude the independent evaluation model.')}</p>
      {agent.token_usage_complete === false && <p className="evaluation-status-note">{c('Token 部分采集：缺失值保留为 —，不计为 0。', 'Partial token usage: missing values remain —, never zero.')}</p>}
      {agent.unavailable_reason && <p className="evaluation-caption">{agent.unavailable_reason}</p>}
      <dl className="evaluation-stat-grid">{usage.map(([label, number]) => <div key={label}><dt>{label}</dt><dd>{value(number)}</dd></div>)}</dl>
    </section>
    <section className="evaluation-report-section"><header><span className="research-section-label">MODEL SERVING</span><h3>{c('模型服务性能', 'Model serving performance')}</h3><span className="evaluation-status-badge">{server.status}</span></header>
      <p className="evaluation-caption">{c('仅汇总相同来源的有效样本；生成速度不是整个服务的吞吐量。TPOT 与 mean ITL 分别展示，不互相补值。', 'Only valid samples from an identical source are aggregated. Generation speed is not system throughput. TPOT and mean ITL remain independent.')}</p>
      <p className="evaluation-caption">{c('调用覆盖：已观测 / 总数 / 已测量', 'Call coverage: observed / total / measured')} {server.observed_model_calls} / {value(server.model_calls_total)} / {server.measured_model_calls} · {server.aggregation} {server.unavailable_reason}</p>
      <div className="evaluation-table-wrap"><table><thead><tr><th>{c('指标', 'Metric')}</th><th>{c('均值', 'Mean')}</th><th>{c('样本', 'Samples')}</th><th>{c('采集来源 / 缺失原因', 'Source / unavailable reason')}</th></tr></thead><tbody>{([
        ['TTFT', server.ttft_ms, ' ms'], ['TPOT', server.tpot_ms, ' ms/token'], ['mean ITL', server.mean_itl_ms, ' ms'], [c('生成速度', 'Generation speed'), server.tokens_per_second, ' tokens/sec'],
      ] as const).map(([label, metric, unit]) => <tr key={label}><th scope="row">{label}</th><td>{value(metric.mean, unit)}</td><td>{metric.samples}</td><td>{metric.source || '—'}{metric.unavailable_reason && <small>{metric.unavailable_reason}</small>}</td></tr>)}</tbody></table></div>
    </section>
    <section className="evaluation-report-section"><header><span className="research-section-label">PROMPT CACHE</span><h3>{c('缓存使用', 'Prompt cache usage')}</h3></header>
      <dl className="evaluation-stat-grid"><div><dt>{c('缓存命中 Token', 'Cache hit tokens')}</dt><dd>{value(server.cache_hit_tokens)}</dd></div><div><dt>{c('查询 Token', 'Query tokens')}</dt><dd>{value(server.cache_query_tokens)}</dd></div><div><dt>{c('缓存命中率', 'Cache hit ratio')}</dt><dd>{value(server.cache_hit_ratio, '%', 100)}</dd></div></dl>
      <p className="evaluation-caption">{c('命中 / 查询', 'Hit / query')}: {value(server.cache_hit_tokens)} / {value(server.cache_query_tokens)} · {c('有效请求覆盖', 'Measured request coverage')}: {server.cache_measured_model_calls} / {value(server.model_calls_total)} · {server.cache_usage_complete ? c('完整采集', 'Complete') : c('部分采集', 'Partial')} {server.cache_unavailable_reason}</p>
      <p className="evaluation-caption">{c('查询 Token 包含缓存命中部分；比率采用后端返回的 Token 加权结果。部分采集仅代表有效配对请求，不能视作完整任务。', 'Query tokens include hits. The ratio is the backend token-weighted result; partial coverage describes only measured request pairs.')}</p>
    </section>
    <section className="evaluation-report-section"><header><span className="research-section-label">GPU SNAPSHOTS</span><h3>{c('GPU 最近利用率快照', 'Latest GPU utilization snapshots')}</h3></header><p className="evaluation-caption">{c('响应完成时的设备采样，可能包含其他进程；不是任务平均值或实时监控。', 'Device snapshots at response completion may include other processes; these are not task averages or live monitoring.')} {server.gpu_scope}</p>
      {server.gpus.length ? <ul className="evaluation-gpus">{server.gpus.map(gpu => <li key={gpu.uuid}><strong>{gpu.uuid}: {value(gpu.utilization_percent, '%')}</strong><span>{c('调用', 'Call')} #{gpu.call_index} · {gpu.sampled_at || '—'}</span></li>)}</ul> : <p className="evaluation-empty">{c('未采集', 'Not collected')}</p>}
    </section>

  </div>;
}
