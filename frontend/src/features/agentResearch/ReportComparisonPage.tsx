import { useCallback } from 'react';
import { Alert, Button, Empty, Skeleton, Tabs } from 'antd';
import { Link, useSearchParams } from 'react-router-dom';
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
  const sameConfig = records ? ['model', 'model_provider', 'context_policy', 'allow_search'].filter(key => config(records[0])[key] != null && config(records[0])[key] === config(records[1])[key]) : [];
  return <div className="report-comparison-page">
    <Link className="back-link" to="/tasks">{c('返回研究记录', 'Back to research records')}</Link>
    <PageHeader title={c('报告对比', 'Report comparison')} description={c('并排阅读两份已有研究，核对结果与证据。', 'Read two existing reports and compare their results and evidence.')} action={<div className="comparison-actions"><Button icon={<ReloadOutlined />} loading={resource.loading} onClick={resource.reload}>{c('刷新', 'Refresh')}</Button><Button icon={<SwapOutlined />} disabled={!ids} onClick={swap}>{c('交换左右', 'Swap sides')}</Button><Link to="/tasks"><Button>{c('更换报告', 'Change reports')}</Button></Link></div>} />
    {!ids ? <Alert showIcon type="warning" title={c('请选择两份不同的报告', 'Select two different reports')} description={c('返回研究记录，勾选两份报告后点击“对比所选报告”。', 'Return to research records, select two reports, then choose Compare selected reports.')} /> : <>
      {resource.loading && !reports && <Skeleton active />}
      {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
      {reports && <>
        <div className="comparison-pair">{reports.map((report, index) => <section className="comparison-report-card" key={report.id} aria-label={c('报告', 'Report') + ' ' + (index ? 'B' : 'A')}>
          <header><strong>{c('报告', 'Report')} {index ? 'B' : 'A'}</strong><WorkflowLabel workflow={workflow(report)} /><Link to={`/tasks/${report.id}`}>{c('打开原报告', 'Open report')}</Link></header>
          <span className="comparison-id">{report.id.slice(0, 8)}</span>
          {report.error && <ErrorNotice error={report.error} retry={resource.reload} />}
          {report.record && <><MathText className="comparison-question">{report.record.question}</MathText>
            <p className="comparison-paper-list">{c('参考论文', 'Papers')}: {report.record.result?.sources.map(source => source.title).filter(Boolean).join(' · ') || c('未提供论文名称', 'Paper titles unavailable')}</p>
            <div className="comparison-config"><p>{c('模型', 'Model')}: {value(config(report.record).model)} · {value(config(report.record).model_provider)}</p><p>{c('上下文策略', 'Context policy')}: {value(config(report.record).context_policy)} · {c('外部搜索', 'External search')}: {value(config(report.record).allow_search)}</p><p>Planner: {value(config(report.record).planner)} · Reflection: {value(config(report.record).reflection)}</p></div>
            {!report.record.result && <Alert type="info" showIcon title={c('此任务尚无可展示的报告正文', 'This task has no report content yet')} description={report.record.error?.message} />}
            {report.record.result && <p className="comparison-note">{c('停止原因', 'Stop reason')}: {report.record.result.stop_reason}</p>}
          </>}
        </section>)}</div>
        {inputs && <Alert className="comparison-conditions" type={inputs.question && inputs.papers === true ? 'info' : 'warning'} showIcon title={inputs.question ? c('问题文本一致', 'Question text matches') : c('问题文本不同，仅供并排阅读', 'Different question text; side-by-side reading only')} description={<><p>{inputs.papers === true ? c('预选论文标识一致；未核实论文顺序、文件版本及动态检索范围。', 'Selected paper IDs match; order, file versions and dynamic retrieval scope are not verified.') : inputs.papers === false ? c('预选论文不同，不能将分差归因为方法差异。', 'Selected papers differ; score differences cannot be attributed to method.') : c('缺少预选论文，无法确认资料范围一致。', 'No selected papers to establish matching inputs.')}</p>{sameConfig.length > 0 && <p>{c('一致的已知配置', 'Matching reported settings')}: {sameConfig.map(key => `${key}: ${value(config(records![0])[key])}`).join(' · ')}</p>}<p>{c('未提供的配置不作推断；同题同论文也不等于受控实验。', 'Unreported settings are not inferred; matching questions and papers do not establish a controlled experiment.')}</p></>} />}
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
