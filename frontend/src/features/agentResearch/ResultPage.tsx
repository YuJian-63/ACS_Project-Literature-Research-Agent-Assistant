import { t, useLocale } from '../../i18n';
import { useEffect, useState } from 'react';
import { Alert, Button, Empty, Skeleton } from 'antd';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { agentResearch, type AgentResearchRecord } from '../../api/agentResearch';
import { asApiError, isCanceled, type ApiError } from '../../api/client';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import { PageHeader } from '../../shared/components/PageHeader';
import ResearchProgress from './ResearchProgress';
import { paperReaderUrl } from '../../shared/lib/paperReader';
import ResultContent from './ResultContent';
export default function ResultPage() {
  useLocale();
  const navigate = useNavigate();
  const { taskId = '' } = useParams();
  const [record, setRecord] = useState<AgentResearchRecord>();
  const [error, setError] = useState<ApiError>();
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [checkedAt, setCheckedAt] = useState<number>();
  useEffect(() => {
    const pending = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined;
    setRecord(undefined); setError(undefined); setLoading(true); setCheckedAt(undefined);
    async function load() {
      let poll = false;
      try {
        const next = await agentResearch.record(taskId, pending.signal);
        if (pending.signal.aborted) return;
        setRecord(next); setError(undefined); setCheckedAt(Date.now());
        poll = next.status === 'queued' || next.status === 'running';
      } catch (failure) { if (!pending.signal.aborted && !isCanceled(failure)) setError(asApiError(failure)); }
      finally { if (!pending.signal.aborted) { setLoading(false); if (poll) timer = setTimeout(() => void load(), 2000); } }
    }
    void load(); return () => { pending.abort(); clearTimeout(timer); };
  }, [taskId, revision]);
  return <><Link className="back-link" to="/tasks">{t('返回任务列表')}</Link>
    <PageHeader title={t('研究结果')} description={t('围绕你的问题，阅读研究内容并核对原文依据。')} action={<Button onClick={() => setRevision(value => value + 1)} loading={loading}>{t('刷新')}</Button>} />
    {error && <ErrorNotice error={error} retry={() => setRevision(value => value + 1)} />}
    {loading && <Skeleton active />}
    {record?.question && <div className="result-question"><span>{t('研究问题')}</span><p>{record.question}</p></div>}
    {(record?.status === 'queued' || record?.status === 'running') && <ResearchProgress queued={record.status === 'queued'} disconnected={Boolean(error)} checkedAt={checkedAt} />}
    {record?.status === 'failed' && <Alert type="error" showIcon title={t('研究未能完成')} description={record.error ? t(record.error.message) : t('请稍后重新创建研究。')} />}
    {record?.result && <ResultContent result={record.result} onReadEvidence={evidence => navigate(paperReaderUrl(evidence.paper_id, { page: evidence.page, researchReturn: { researchId: taskId, citationKey: evidence.chunk_id } }))} />}
    {record?.status === 'succeeded' && !record.result && <Empty description={t('尚未取得研究结果，请刷新重试。')} />}
  </>;
}
