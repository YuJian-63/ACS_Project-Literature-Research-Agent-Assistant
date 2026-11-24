import { useCallback } from 'react';
import { Alert, Button, Empty, Skeleton, Tabs } from 'antd';
import { Link, useSearchParams } from 'react-router-dom';
import ReportPdfExport from './ReportPdfExport';
import ComparisonPaperList from './ComparisonPaperList';
import { withComparisonReturn } from '../../shared/lib/comparisonReturn';
import { ReloadOutlined, SwapOutlined } from '@ant-design/icons';
import { agentResearch, type AgentResearchRecord, type ResearchWorkflowType } from '../../api/agentResearch';
import { asApiError, type ApiError } from '../../api/client';
import { useLocale } from '../../i18n';
import { useResource } from '../../shared/hooks/useResource';
import { PageHeader } from '../../shared/components/PageHeader';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import MathText from '../../shared/components/MathText';
import { shouldPollResearch } from '../../shared/lib/taskMetrics';
import { comparisonIds, matchingInputs, reportedConfig } from './lib/reportComparison';
import { WorkflowLabel } from './RecordWorkflow';
import { ComparisonMetrics } from './ComparisonMetrics';
import ComparedReport from './ComparedReport';
import './comparison.css';

type Report = { id: string; record?: AgentResearchRecord; workflow?: ResearchWorkflowType; error?: ApiError };
const poll = (reports: Report[]) => reports.some(report => report.record && shouldPollResearch(report.record));
const sections = [['answer', '研究正文', 'Research text'], ['comparison', '论文比较', 'Paper comparison'], ['unresolved', '待解决问题', 'Open questions'], ['sources', '引用与来源', 'Citations & sources'], ['evaluation', '研究评估', 'Evaluation'], ['execution', '运行记录', 'Execution log']] as const;

export default function ReportComparisonPage() {
  const locale = useLocale();
  const c = (zh: string, en: string) => locale === 'en-US' ? en : zh;
  const [parameters, setParameters] = useSearchParams();
  const ids = comparisonIds(parameters);
  const a = ids?.[0], b = ids?.[1];
  const load = useCallback(async (signal: AbortSignal): Promise<Report[]> => {
    if (!a || !b) return [];
    return Promise.all([a, b].map(async id => {
      const [record, detail] = await Promise.allSettled([agentResearch.record(id, signal), agentResearch.workflow(id, signal)]);
      return { id, record: record.status === 'fulfilled' ? record.value : undefined,
        workflow: detail.status === 'fulfilled' ? detail.value.workflow_type : undefined,
        error: record.status === 'rejected' ? asApiError(record.reason) : undefined };
    }));
  }, [a, b]);
  const resource = useResource(load, 30_000, poll);
  // Ignore a previous pair while the new URL's request starts.
  const reports = resource.data?.length === 2 && resource.data[0]?.id === a && resource.data[1]?.id === b ? resource.data : undefined;
  const records = reports?.every(report => report.record) ? reports.map(report => report.record!) as [AgentResearchRecord, AgentResearchRecord] : undefined;
  const inputs = records ? matchingInputs(...records) : undefined;
  const section = sections.some(([key]) => key === parameters.get('section')) ? parameters.get('section')! : 'answer';
  const value = (input: unknown) => typeof input === 'boolean' ? input ? c('开', 'On') : c('关', 'Off') : typeof input === 'string' || typeof input === 'number' ? String(input) : c('未提供', 'Not provided');
  function workflow(report: Report) {
    const recorded = report.record?.result?.configuration.workflow;
    return report.workflow ?? (recorded === 'baseline' ? 'baseline' : recorded === 'extension' ? 'extended' : undefined);
  }
  function swap() { setParameters(previous => { const next = new URLSearchParams(previous); next.set('a', b!); next.set('b', a!); return next; }); }
  const config = reportedConfig;
  const returnUrl = '/tasks/compare?' + parameters;
  const contextLabel = (input: unknown) => input === 'CompactHistory' || input === 'compact' ? c('压缩上下文', 'Compact history') : input === 'FullHistory' || input === 'full' ? c('完整上下文', 'Full history') : value(input);
  const providerLabel = (input: unknown) => input === 'tacc' ? c('课程 TACC', 'Course TACC') : input === 'bailian' ? c('百炼', 'Bailian') : input === 'custom' ? c('自定义服务', 'Custom service') : value(input);
  return <div className="report-comparison-page">
    <Link className="comparison-return-entry" to="/tasks">{c('返回研究记录', 'Back to research records')}</Link>
    <PageHeader title={c('报告对比', 'Report comparison')} description={c('并排阅读两份已有研究，核对结果与证据。', 'Read two existing reports and compare their results and evidence.')} action={<div className="comparison-actions"><ReportPdfExport records={records ?? []} disabled={resource.loading} /><Button icon={<ReloadOutlined />} loading={resource.loading} onClick={resource.reload}>{c('刷新', 'Refresh')}</Button><Button icon={<SwapOutlined />} disabled={!ids} onClick={swap}>{c('交换左右', 'Swap sides')}</Button><Link to="/tasks"><Button>{c('更换报告', 'Change reports')}</Button></Link></div>} />
    {!ids ? <Alert showIcon type="warning" title={c('请选择两份不同的报告', 'Select two different reports')} description={c('返回研究记录，勾选两份报告后点击“对比所选报告”。', 'Return to research records, select two reports, then choose Compare selected reports.')} /> : <>
      {resource.loading && !reports && <Skeleton active />}
      {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
      {reports && <>
        <div className="comparison-pair">{reports.map((report, index) => <section className="comparison-report-card" key={report.id} aria-label={c('报告', 'Report') + ' ' + (index ? 'B' : 'A')}>
          <header><strong>{c('报告', 'Report')} {index ? 'B' : 'A'}</strong><WorkflowLabel workflow={workflow(report)} /><Link to={withComparisonReturn(`/tasks/${report.id}`, returnUrl)}>{c('打开原报告', 'Open report')}</Link></header>
          <span className="comparison-id">{c('任务编号', 'Task ID')}: {report.id.slice(0, 8)}</span>
          {report.error && <ErrorNotice error={report.error} retry={resource.reload} />}
          {report.record && <><div className="comparison-question-block"><span className="comparison-field-label">{c('研究问题', 'Research question')}</span><MathText className="comparison-question">{report.record.question}</MathText></div>
            <div className="comparison-papers-block"><span className="comparison-field-label">{c('参考论文', 'Reference papers')}</span><ComparisonPaperList record={report.record} returnUrl={returnUrl} /></div>
            <dl className="comparison-settings">
              <div className="comparison-setting-model"><dt>{c('研究模型', 'Research model')}</dt><dd>{value(config(report.record).model)}<small>{providerLabel(config(report.record).model_provider)}</small></dd></div>
              <div><dt>{c('上下文策略', 'Context policy')}</dt><dd>{contextLabel(config(report.record).context_policy)}</dd></div>
              <div><dt>{c('外部搜索', 'External search')}</dt><dd><span className="comparison-setting-value" data-enabled={config(report.record).allow_search}>{value(config(report.record).allow_search)}</span></dd></div>
              <div><dt>{c('规划 Planner', 'Planner')}</dt><dd><span className="comparison-setting-value" data-enabled={config(report.record).planner}>{value(config(report.record).planner)}</span></dd></div>
              <div><dt>{c('复核 Reflection', 'Reflection')}</dt><dd><span className="comparison-setting-value" data-enabled={config(report.record).reflection}>{value(config(report.record).reflection)}</span></dd></div>
            </dl>
            {!report.record.result && <Alert type="info" showIcon title={c('此任务尚无可展示的报告正文', 'This task has no report content yet')} description={report.record.error?.message} />}
          </>}
        </section>)}</div>
        {records && <ComparisonMetrics records={records} comparableInputs={Boolean(inputs?.question && inputs.papers === true)} />}
        <Tabs className="comparison-section-tabs" activeKey={section} onChange={key => setParameters(previous => { const next = new URLSearchParams(previous); next.set('section', key); return next; }, { replace: true })} items={sections.map(([key, zh, en]) => ({ key, label: c(zh, en) }))} />
        <div className="comparison-pair comparison-reading">{reports.map((report, index) => <section className="comparison-reading-pane" key={report.id} aria-label={`${c('报告', 'Report')} ${index ? 'B' : 'A'} · ${section}`}><header><strong>{c('报告', 'Report')} {index ? 'B' : 'A'}</strong><WorkflowLabel workflow={workflow(report)} /></header>
          {report.record?.result ? <ComparedReport key={report.id} record={report.record} section={section} onRequested={resource.reload} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={c('没有可展示的报告内容', 'No report content available')} />}
        </section>)}</div>
        <p className="comparison-note">{c('本页不会自动重新执行研究或申请评分。评分页签中的操作由你手动触发。', 'This page does not automatically run research or request evaluation. Evaluation actions are manual.')}</p>
      </>}
    </>}
  </div>;
}
