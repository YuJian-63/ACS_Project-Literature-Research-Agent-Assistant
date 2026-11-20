import { errorText } from '../../../i18n/diagnostics';
import { t, useLocale } from '../../../i18n';
import { lazy, Suspense, useCallback, useState } from 'react';
import { Alert, Button, Empty, Skeleton, Spin, Tabs } from 'antd';
import { ArrowLeftOutlined, BookOutlined, FileTextOutlined, ReloadOutlined, TableOutlined } from '@ant-design/icons';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../../../api/client';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { MockTag } from '../../../shared/components/MockTag';
import { PageHeader } from '../../../shared/components/PageHeader';
import { StatusBadge } from '../../../shared/components/StatusBadge';
import EvidenceCoverageNotice from '../components/EvidenceCoverageNotice';
import { useResource } from '../../../shared/hooks/useResource';
import { useTask } from '../hooks/useTask';
import { dateTime, isTerminal, taskTypeLabels } from '../../../shared/lib/format';

import TaskProgress from '../components/TaskProgress';

const ArtifactView = lazy(() => import('../components/ArtifactView'));

function TaskDetail({ taskId }: { taskId: string }) {
  useLocale();
  const state = useTask(taskId);
  const task = state.task;
  const [parameters] = useSearchParams();
  const [view, setView] = useState(() => parameters.get('view') === 'compare' ? 'compare' : 'read');
  const ids = task?.status === 'succeeded' ? task.paper_ids.join(',') : '';
  const loadPapers = useCallback((signal: AbortSignal) => Promise.all(ids.split(',').filter(Boolean).map((id) => api.paper(id, signal))), [ids]);
  const inputs = useResource(loadPapers);
  const hasComparison = state.artifacts?.some((artifact) => artifact.comparison_table);
  const complete = task?.status === 'succeeded';
  function result(resultView: 'read' | 'compare') {
    return <section className="result-panel">
      {state.artifactError ? <ErrorNotice error={state.artifactError} title={t('结果查询失败，任务仍为已完成')} retry={state.refresh} /> : state.artifacts === undefined ? <Skeleton active paragraph={{ rows: 5 }} /> : state.artifacts.length ? <Suspense fallback={<Spin><div className="loading-placeholder" /></Spin>}>{state.artifacts.map((artifact) => <ArtifactView key={artifact.id} artifact={artifact} papers={inputs.data ?? []} view={resultView} />)}</Suspense> : <Alert type="warning" showIcon title={t('尚未取得任务产物，请重试查询。')} action={<Button onClick={state.refresh}>{t('重试查询')}</Button>} />}
    </section>;
  }
  return <>
    <Link to="/tasks" className="back-link"><ArrowLeftOutlined />{t('返回任务列表')}</Link>
    <PageHeader title={task ? t(state.artifacts?.[0]?.title ?? taskTypeLabels()[task.task_type]) : t('任务详情')} description={t('查看任务状态、资料来源与已保存的研究结果。')} action={<div className="detail-actions">{task && isTerminal(task.status) && <Link to={'/tasks/new?from_task=' + task.id}><Button>{t('重新创建任务')}</Button></Link>}<Button icon={<ReloadOutlined />} onClick={state.refresh} loading={state.refreshing}>{t('刷新')}</Button></div>} />
    {state.queryError && <ErrorNotice error={state.queryError} retry={state.refresh} title={task ? t('查询失败，保留上次成功查询的任务状态') : t('任务查询失败')} />}
    {!task ? state.loading && <section className="content-panel"><Skeleton active paragraph={{ rows: 6 }} /></section> : <>
      <section className="task-overview" aria-label={t('任务状态')}><div className="task-overview-main"><StatusBadge status={task.status} />{task.is_mock && <MockTag />}</div><div className="task-overview-meta"><span><BookOutlined /> {t('{0} 篇', [task.paper_ids.length])}</span><span>{t('创建于 {0}', [dateTime(task.created_at)])}</span></div></section>
      {task.question && <div className="result-question"><span>{t('研究问题')}</span><p>{task.question}</p></div>}
      {task.is_mock && <Alert className="inline-alert" type="warning" showIcon title={t('模拟运行与模拟结果')} description={t('尚未解析或分析论文，未调用模型。以下内容用于验证流程，不应作为研究结论或模型效果指标。')} />}
      {task.status === 'failed' && task.error && <Alert type="error" showIcon className="inline-alert" title={t('任务执行失败 · {0}', [task.error.code])} description={t('{0}。可重新创建任务，原任务记录会保留。', [errorText(task.error)])} />}
      {complete && <EvidenceCoverageNotice task={task} papers={inputs.data ?? []} />}
      {complete ? <>
        {inputs.error && <ErrorNotice error={inputs.error} title={t('论文信息查询失败')} retry={inputs.reload} />}
        <Tabs className="result-tabs" activeKey={view === 'compare' && !hasComparison ? 'read' : view} onChange={setView} destroyOnHidden items={[
          { key: 'read', label: t(task.task_type === 'review' ? '综述正文' : '研究结果'), icon: <FileTextOutlined aria-hidden />, children: result('read') },
          ...(hasComparison ? [{ key: 'compare', label: t('论文比较'), icon: <TableOutlined aria-hidden />, children: result('compare') }] : []),
        ]} />
      </> : task.status === 'queued' || task.status === 'running' ? <TaskProgress queued={task.status === 'queued'} disconnected={Boolean(state.queryError)} checkedAt={state.checkedAt} /> : <section className="content-panel waiting-panel"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('此任务没有生成研究结果')} /></section>}
    </>}
  </>;
}

export default function TaskDetailPage() {
  useLocale();
  const { taskId = '' } = useParams();
  return <TaskDetail key={taskId} taskId={taskId} />;
}
