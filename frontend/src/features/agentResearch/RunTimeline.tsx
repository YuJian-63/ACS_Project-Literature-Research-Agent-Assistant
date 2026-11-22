import type { AgentResult } from '../../api/agentResearch';
import { t } from '../../i18n';

type TraceEntry = Record<string, unknown>;

const kindLabels: Record<string, string> = {
  model: '模型调用', tool: '工具调用', context: '上下文处理', planner: '研究规划', reflection: '结果复核',
};

function traceEvents(trace: unknown[]) {
  return trace.flatMap((value) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
    const entry = value as TraceEntry;
    if (typeof entry.kind !== 'string') return [];
    const name = [entry.name, entry.purpose, entry.action].find((part) => typeof part === 'string' && part.trim());
    const observation = entry.observation;
    const failed = typeof entry.error === 'string' || Boolean(observation && typeof observation === 'object' && !Array.isArray(observation) && 'error' in observation);
    const elapsed = typeof entry.elapsed_seconds === 'number' && Number.isFinite(entry.elapsed_seconds) ? entry.elapsed_seconds : null;
    return [{ kind: entry.kind, name: typeof name === 'string' ? name : '', outcome: typeof entry.outcome === 'string' ? entry.outcome : '', failed, elapsed }];
  });
}

function number(value: number | null) {
  return value === null ? '—' : new Intl.NumberFormat().format(value);
}

export default function RunTimeline({ result }: { result: AgentResult }) {
  const config = result.configuration;
  const modelSource = config.model_provider === 'custom' ? t('指定服务地址') : config.model_provider === 'tacc' ? t('课程 Qwen') : config.model_provider === 'bailian' ? t('百炼') : '';
  const model = typeof config.model === 'string' ? config.model : '';
  const workflow = config.workflow === 'extension' ? 'Extension' : 'Baseline';
  const events = traceEvents(result.trace);
  const outcome = result.stop_reason === 'completed' ? t('已完成') : result.stop_reason === 'partial' ? t('部分完成') : t('已停止');
  return <section className="research-run-timeline">
    <header className="research-run-heading"><div><span className="research-section-label">RUN DETAILS</span><h2>{t('研究执行过程')}</h2><div className="research-run-meta"><span className="research-run-status">{outcome}</span><span>{[workflow, modelSource, model].filter(Boolean).join(' · ')}</span></div></div><div className="research-run-duration"><strong>{Number.isFinite(result.usage.elapsed_seconds) ? result.usage.elapsed_seconds.toFixed(1) : '—'}</strong><span>{t('秒')}</span></div></header>
    <dl className="research-run-metrics"><div><dt>{t('模型调用')}</dt><dd>{number(result.usage.model_calls)}</dd></div><div><dt>{t('工具调用')}</dt><dd>{number(result.usage.tool_calls)}</dd></div><div><dt>{t('输入 Token')}</dt><dd>{number(result.usage.input_tokens)}</dd></div><div><dt>{t('输出 Token')}</dt><dd>{number(result.usage.output_tokens)}</dd></div></dl>
    {typeof config.persistence === 'string' && <p className="research-run-persistence">{config.persistence === 'saved' ? t('Agent 数据库已保存') : t('Agent 数据库写入失败')}</p>}
    {result.errors.length > 0 && <section className="research-run-errors"><h3>{t('执行中记录的错误')}</h3><ul>{result.errors.map((error, index) => <li key={index}>{error.stage} · {error.type}</li>)}</ul></section>}
    <div className="research-run-list-heading"><h3>{t('执行步骤')}</h3><span>{t('共 {0} 步', [events.length])}</span></div>
    {events.length ? <ol className="research-run-events">{events.map((event, index) => <li key={index} className={event.failed ? 'is-error' : ''}><span className="research-run-dot" aria-hidden /><div className="research-run-event"><div><strong>{t(kindLabels[event.kind] || event.kind)}{event.name && <> · <code>{event.name}</code></>}</strong><span className="research-run-sequence">{String(index + 1).padStart(2, '0')}</span></div>{(event.outcome || event.failed || event.elapsed !== null) && <p>{event.failed && <span className="research-run-error-tag">{t('错误')}</span>}{event.outcome && <span>{event.outcome}</span>}{event.elapsed !== null && <span>{event.elapsed.toFixed(2)} s</span>}</p>}</div></li>)}</ol> : <p className="research-run-empty">{t('暂无执行步骤记录')}</p>}
  </section>;
}
