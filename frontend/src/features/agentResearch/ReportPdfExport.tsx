import { useEffect, useRef, useState } from 'react';
import { createPortal, flushSync } from 'react-dom';
import { Button, App } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import type { AgentResearchRecord } from '../../api/agentResearch';
import { evaluations, type EvaluationVersion } from '../../api/evaluations';
import { api } from '../../api/client';
import { useLocale } from '../../i18n';
import MathText from '../../shared/components/MathText';
import { StatusBadge } from '../../shared/components/StatusBadge';
import { resolveResearchSource } from './lib/researchSource';
import { reportedConfig, matchingInputs } from './lib/reportComparison';
import { ComparisonMetrics } from './ComparisonMetrics';
import { EvaluationReportView } from './EvaluationPanel';
import ResultContent from './ResultContent';
import './report-pdf.css';

const sections = [['answer', '研究正文', 'Research text'], ['comparison', '论文比较', 'Paper comparison'], ['unresolved', '待解决问题', 'Open questions'], ['sources', '引用与来源', 'Citations and sources'], ['evaluation', '研究评估', 'Evaluation'], ['execution', '运行记录', 'Execution log']] as const;
type Snapshot = { records: AgentResearchRecord[]; versions: (EvaluationVersion | undefined)[]; issues: boolean[]; titles: Record<string, string>; timestamp: string };
export default function ReportPdfExport({ records, disabled = false }: { records: AgentResearchRecord[]; disabled?: boolean }) {
  const locale = useLocale();
  const c = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const pending = useRef<AbortController | null>(null);
  const releasePrint = useRef<(() => void) | null>(null);
  const documentRef = useRef<HTMLDivElement>(null);
  useEffect(() => () => { pending.current?.abort(); releasePrint.current?.(); }, []);
  async function download() {
    if (pending.current || !records.length || records.some(record => !record.result)) return;
    const controller = new AbortController(); pending.current = controller; setBusy(true);
    const title = document.title;
    let printing = false;
    try {
      const paperIds = new Set<string>();
      records.forEach(record => { record.paper_ids.forEach(id => paperIds.add(id)); record.result?.sources.forEach(source => { const resolved = resolveResearchSource(source); if (resolved.kind === 'local') paperIds.add(resolved.paperId); }); });
      const [reports, papers] = await Promise.all([
        Promise.allSettled(records.map(record => record.metrics?.evaluation.evaluation_id ? evaluations.get(record.task_id, record.metrics.evaluation.evaluation_id, controller.signal) : Promise.resolve(undefined))),
        Promise.allSettled([...paperIds].map(async id => [id, (await api.paper(id, controller.signal)).title] as const)),
      ]);
      if (controller.signal.aborted) return;
      const titles = Object.fromEntries(papers.flatMap(paper => paper.status === 'fulfilled' ? [paper.value] : []));
      flushSync(() => setSnapshot({ records: [...records], versions: reports.map(report => report.status === 'fulfilled' ? report.value : undefined), issues: reports.map(report => report.status === 'rejected'), titles, timestamp: new Date().toLocaleString(locale) }));
      documentRef.current?.querySelectorAll('details').forEach(detail => { detail.open = true; });
      await document.fonts.ready;
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      if (controller.signal.aborted) return;
      document.title = (records.length === 2 ? 'Report-comparison-' : 'Research-report-') + records.map(record => record.task_id.slice(0, 8)).join('-');
      const finish = () => {
        document.title = title;
        window.removeEventListener('afterprint', finish);
        releasePrint.current = null;
        if (!controller.signal.aborted) { setSnapshot(undefined); setBusy(false); }
        if (pending.current === controller) pending.current = null;
      };
      releasePrint.current = finish;
      window.addEventListener('afterprint', finish);
      printing = true;
      window.print();
    } catch {
      printing = false; releasePrint.current?.();
      if (!controller.signal.aborted) void message.error(c('PDF 导出准备失败，请重试。', 'Could not prepare the PDF. Please try again.'));
    } finally {
      if (!printing) document.title = title;
      if (!printing && !controller.signal.aborted) { setSnapshot(undefined); setBusy(false); }
      if (!printing && pending.current === controller) pending.current = null;
    }
  }
  const value = (input: unknown) => typeof input === 'boolean' ? input ? c('开', 'On') : c('关', 'Off') : typeof input === 'string' || typeof input === 'number' ? String(input) : c('未提供', 'Not provided');
  const pair = snapshot?.records.length === 2;
  return <><Button icon={<DownloadOutlined aria-hidden />} aria-label={c('导出 PDF', 'Export PDF')} loading={busy} disabled={disabled || !records.length || records.some(record => !record.result)} onClick={() => void download()}>{c('导出 PDF', 'Export PDF')}</Button>
    {snapshot && createPortal(<div ref={documentRef} className="research-pdf-export" data-comparison={pair}>
      <h1>{pair ? c('报告对比', 'Report comparison') : c('研究报告', 'Research report')}</h1><p className="pdf-generated">{c('导出时间', 'Exported')}: {snapshot.timestamp}</p>
      <div className="pdf-report-pair">{snapshot.records.map((record, index) => {
        const config = reportedConfig(record);
        const paperNames = new Set([...(record.result?.sources.map(source => { const resolved = resolveResearchSource(source); return resolved.kind === 'local' ? snapshot.titles[resolved.paperId] || source.title : source.title; }) ?? []), ...record.paper_ids.map(id => snapshot.titles[id]).filter(Boolean)]);
        return <section key={record.task_id} className="pdf-report-header"><h2>{pair ? c('报告', 'Report') + ' ' + (index ? 'B' : 'A') : c('任务信息', 'Task information')} · {config.workflow === 'extension' ? 'Extension' : config.workflow === 'baseline' ? 'Baseline' : c('流程未提供', 'Workflow unavailable')}</h2><p>ID: {record.task_id}</p><StatusBadge status={record.status} /><h3>{c('研究问题', 'Research question')}</h3><MathText>{record.question}</MathText><h3>{c('参考论文', 'Reference papers')}</h3><ul>{[...paperNames].map(name => <li key={name}>{name}</li>)}</ul><p>{c('研究模型', 'Model')}: {value(config.model)} · {value(config.model_provider)}</p><p>{c('上下文策略', 'Context policy')}: {value(config.context_policy)} · {c('外部搜索', 'Search')}: {value(config.allow_search)}</p><p>Planner: {value(config.planner)} · Reflection: {value(config.reflection)}</p></section>;
      })}</div>
      {pair && <ComparisonMetrics records={snapshot.records as [AgentResearchRecord, AgentResearchRecord]} comparableInputs={Boolean(matchingInputs(snapshot.records[0], snapshot.records[1]).question && matchingInputs(snapshot.records[0], snapshot.records[1]).papers)} />}
      {sections.map(([key, zh, en]) => <section className="pdf-section" key={key} data-pdf-section={key}><h2 className="pdf-section-title">{c(zh, en)}</h2><div className="pdf-report-pair">{snapshot.records.map((record, index) => <section className="pdf-report-content" key={record.task_id}>{pair && <h3>{c('报告', 'Report')} {index ? 'B' : 'A'}</h3>}{key === 'evaluation' ? <>{snapshot.issues[index] && <p>{c('完整评分报告读取失败，以下仅包含已取得的评分摘要。', 'Full evaluation report could not be loaded; only the available summary is included.')}</p>}<EvaluationReportView metrics={record.metrics} version={snapshot.versions[index]} /></> : <ResultContent result={record.result!} metrics={record.metrics} section={key} />}</section>)}</div></section>)}
    </div>, document.body)}
  </>;
}
