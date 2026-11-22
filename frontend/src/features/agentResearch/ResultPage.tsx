import { shouldPollResearch } from '../../shared/lib/taskMetrics';
import { t, useLocale } from '../../i18n';
import { useEffect, useState } from 'react';
import { Alert, Button, Empty, Skeleton } from 'antd';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { agentResearch, type AgentResearchRecord, type AgentSource } from '../../api/agentResearch';
import { asApiError, isCanceled, type ApiError } from '../../api/client';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import { PageHeader } from '../../shared/components/PageHeader';
import ResearchProgress from './ResearchProgress';
import { paperReaderUrl } from '../../shared/lib/paperReader';
import ResultContent from './ResultContent';
import MathText from '../../shared/components/MathText';
import SourceImportDialog from './SourceImportDialog';
import { resolveResearchSource } from './lib/researchSource';

type ReadingTarget = { source: AgentSource; page?: number; citationKey?: string };
export default function ResultPage() {
  useLocale();
  const navigate = useNavigate();
  const { taskId = '' } = useParams();
  const [record, setRecord] = useState<AgentResearchRecord>();
  const [error, setError] = useState<ApiError>();
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [checkedAt, setCheckedAt] = useState<number>();
  const [readingTarget, setReadingTarget] = useState<ReadingTarget>();
  function openPaper(paperId: string, target: ReadingTarget) {
    setReadingTarget(undefined);
    navigate(paperReaderUrl(paperId, { page: target.page,
      researchReturn: { researchId: taskId, citationKey: target.citationKey } }));
  }
  function readSource(target: ReadingTarget) {
    const resolved = resolveResearchSource(target.source);
    if (resolved.kind === 'local') openPaper(resolved.paperId, target);
    else setReadingTarget(target);
  }
  useEffect(() => {
    setReadingTarget(undefined);
  }, [taskId]);
  useEffect(() => {
    const pending = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined;
    setRecord(undefined); setError(undefined); setLoading(true); setCheckedAt(undefined);
    async function load() {
      let poll = false;
      try {
        const next = await agentResearch.record(taskId, pending.signal);
        if (pending.signal.aborted) return;
        setRecord(next); setError(undefined); setCheckedAt(Date.now());
        poll = shouldPollResearch(next);
      } catch (failure) { if (!pending.signal.aborted && !isCanceled(failure)) setError(asApiError(failure)); }
      finally { if (!pending.signal.aborted) { setLoading(false); if (poll) timer = setTimeout(() => void load(), 30_000); } }
    }
    void load(); return () => { pending.abort(); clearTimeout(timer); };
  }, [taskId, revision]);
  return <><Link className="back-link" to="/tasks">{t('返回任务列表')}</Link>
    <PageHeader title={t('研究结果')} description={t('围绕你的问题，阅读研究内容并核对原文依据。')} action={<Button onClick={() => setRevision(value => value + 1)} loading={loading}>{t('刷新')}</Button>} />
    {error && <ErrorNotice error={error} retry={() => setRevision(value => value + 1)} />}
    {loading && <Skeleton active />}
    {record?.question && <div className="result-question"><span>{t('研究问题')}</span><MathText>{record.question}</MathText></div>}
    {(record?.status === 'queued' || record?.status === 'running') && <ResearchProgress queued={record.status === 'queued'} disconnected={Boolean(error)} checkedAt={checkedAt} />}
    {record?.status === 'failed' && <Alert type="error" showIcon title={t('研究未能完成')} description={record.error ? t(record.error.message) : t('请稍后重新创建研究。')} />}
    {record?.result && <ResultContent key={taskId} result={record.result} metrics={record.metrics}
      onReadEvidence={evidence => readSource({ source: evidence, page: evidence.page, citationKey: evidence.chunk_id })}
      onReadSource={source => readSource({ source })} />}
    {readingTarget && <SourceImportDialog key={taskId + ':' + readingTarget.source.source_id + ':' + (readingTarget.citationKey || '')}
      source={readingTarget.source} page={readingTarget.page} onClose={() => setReadingTarget(undefined)}
      onRead={paperId => openPaper(paperId, readingTarget)} />}
    {record?.status === 'succeeded' && !record.result && <Empty description={t('尚未取得研究结果，请刷新重试。')} />}
  </>;
}
