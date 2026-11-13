import { errorText, eventText } from '../i18n/diagnostics';
import { t, useLocale, getLocale } from '../i18n';
import { lazy, Suspense, useCallback } from 'react';
import { Alert, Button, Empty, Skeleton, Spin, Timeline } from 'antd';
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link, useParams } from 'react-router-dom';
import { api, paperFileUrl } from '../api/client';
import type { Task } from '../api/types';
import { ErrorNotice, MockTag, PageHeader, StatusBadge } from '../components/Common';
import { useResource } from '../hooks/useResource';
import { useTask } from '../hooks/useTask';
import { dateTime, duration, isTerminal, stageLabels, taskTypeLabels } from '../lib/format';

const ArtifactView = lazy(() => import('../components/ArtifactView'));

function TaskInputs({ task }: { task: Task }) {
  useLocale();
  const ids = task.paper_ids.join(',');
  const load = useCallback((signal: AbortSignal) => Promise.all(ids.split(',').filter(Boolean).map((id) => api.paper(id, signal))), [ids]);
  const resource = useResource(load);
  return <section className="content-panel input-panel"><h2>{t("研究输入")}</h2>
    {task.question && <p className="research-question">{task.question}</p>}
    <h3>{t("选定论文")} <span>{t("{0} 篇", [task.paper_ids.length])}</span></h3>
    {resource.error && <ErrorNotice error={resource.error} title={t("论文信息查询失败")} retry={resource.reload} />}
    {resource.loading ? <Skeleton active title={false} paragraph={{ rows: 2 }} /> : <ul className="source-papers">{resource.data?.map((paper) => <li key={paper.id}><a href={paperFileUrl(paper.id)} target="_blank" rel="noopener noreferrer">{paper.title}</a><span>{t("查看 PDF")}</span></li>)}</ul>}
    <p className="section-footnote">{t("预算：{0} 步 · {1} Token · {2} 秒执行超时", [task.budget.max_steps, task.budget.max_tokens.toLocaleString(getLocale()), task.budget.timeout_seconds])}</p>
  </section>;
}

function TaskDetail({ taskId }: { taskId: string }) {
  useLocale();
  const state = useTask(taskId);
  const task = state.task;
  return <>
    <Link to="/tasks" className="back-link"><ArrowLeftOutlined />{t("返回任务列表")}</Link>
    <PageHeader title={task ? taskTypeLabels()[task.task_type] : t("任务详情")} description={t("查看任务状态、资料来源与已保存的研究结果。")} action={<div className="detail-actions">{task && isTerminal(task.status) && <Link to={`/tasks/new?from_task=${task.id}`}><Button>{t("重新创建任务")}</Button></Link>}<Button icon={<ReloadOutlined />} onClick={state.refresh} loading={state.refreshing}>{t("刷新")}</Button></div>} />
    {state.queryError && <ErrorNotice error={state.queryError} retry={state.refresh} title={task ? t("查询失败，保留上次成功查询的任务状态") : t("任务查询失败")} />}
    {!task ? state.loading && <section className="content-panel"><Skeleton active paragraph={{ rows: 6 }} /></section> : <>
      <section className="task-overview" aria-label={t("任务状态")}><div className="task-overview-main"><StatusBadge status={task.status} />{task.is_mock && <MockTag />}<span className="task-stage">{stageLabels()[task.stage] || task.stage}</span></div><div className="task-overview-meta"><span>{t("创建于 {0}", [dateTime(task.created_at)])}</span><span className="identifier">{task.id}</span></div></section>
      {task.is_mock && <Alert className="inline-alert" type="warning" showIcon title={t("模拟运行与模拟结果")} description={t("尚未解析或分析论文，未调用模型。以下内容用于验证流程，不应作为研究结论或模型效果指标。")} />}
      {task.status === 'failed' && task.error && <Alert type="error" showIcon className="inline-alert" title={t("任务执行失败 · {0}", [task.error.code])} description={<>{t("{0}。可重新创建任务，原任务记录会保留。", [errorText(task.error)])}</>} />}
      <div className="detail-layout"><div className="detail-main">
        <section className="content-panel result-panel">
          {task.status === 'succeeded' ? <>
            {state.artifactError ? <ErrorNotice error={state.artifactError} title={t("结果查询失败，任务仍为已完成")} retry={state.refresh} /> : state.artifacts === undefined ? <Skeleton active paragraph={{ rows: 5 }} /> : state.artifacts.length ? <Suspense fallback={<Spin><div className="loading-placeholder" /></Spin>}>{state.artifacts.map((artifact) => <ArtifactView key={artifact.id} artifact={artifact} />)}</Suspense> : <Alert type="warning" showIcon title={t("尚未取得任务产物，请重试查询。")} action={<Button onClick={state.refresh}>{t("重试查询")}</Button>} />}
          </> : <><div className="panel-heading"><h2>{t("研究结果")}</h2></div><div className="waiting-result"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={task.status === 'queued' ? t("任务正在等待执行") : task.status === 'running' ? t("任务执行中，结果尚未生成") : t("此任务没有生成研究结果")} /><p>{task.status === 'queued' ? t("请确认对应的后端 Worker 已启动。排队期间可以离开页面，稍后按任务 ID 恢复查询。") : task.status === 'running' ? t("页面会在每次查询完成后等待 2 秒再刷新，执行记录持续保存在后端。") : t("请查看失败原因，调整输入或预算后重新创建任务。")}</p></div></>}
        </section>
        <TaskInputs task={task} />
      </div><aside className="detail-aside">
        <section className="content-panel trace-panel"><div className="panel-heading"><h2>{t("执行记录")}</h2><span>{t("{0} 条", [state.events.length])}</span></div>
          {state.eventError && <ErrorNotice error={state.eventError} title={t("执行记录查询失败")} retry={state.refresh} />}
          {state.events.length ? <Timeline items={state.events.map((event) => ({ key: event.seq, color: event.event_type === 'error' ? 'red' : event.status === 'succeeded' ? 'green' : 'blue', content: <div className="trace-event"><span>{dateTime(event.created_at)} · #{event.seq}</span><p>{eventText(event)}</p></div> }))} /> : <p className="muted">{t("尚未取得执行记录。")}</p>}
        </section>
        <section className="content-panel stats-panel"><h2>{t("实际运行统计")}</h2><dl><div><dt>{t("排队耗时")}</dt><dd>{duration(task.stats.queue_ms)}</dd></div><div><dt>{t("执行耗时")}</dt><dd>{duration(task.stats.execution_ms)}</dd></div><div><dt>{t("总耗时")}</dt><dd>{duration(task.stats.end_to_end_ms)}</dd></div><div><dt>{t("输入 / 输出 Token")}</dt><dd>{task.stats.input_tokens ?? '—'} / {task.stats.output_tokens ?? '—'}</dd></div><div><dt>{t("模型 / 工具调用")}</dt><dd>{task.stats.model_calls ?? '—'} / {task.stats.tool_calls ?? '—'}</dd></div></dl><p className="section-footnote">{t("“—”表示没有报告或未发生测量，不等同于 0。")}</p><div className="version-note">{t("工作流：")}{task.versions.workflow_version}<br />{t("模型：")}{task.versions.model_id || (task.is_mock ? t("未调用模型") : t("未报告"))}</div></section>
      </aside></div>
    </>}
  </>;
}

export default function TaskDetailPage() {
  useLocale();
  const { taskId = '' } = useParams();
  return <TaskDetail key={taskId} taskId={taskId} />;
}
