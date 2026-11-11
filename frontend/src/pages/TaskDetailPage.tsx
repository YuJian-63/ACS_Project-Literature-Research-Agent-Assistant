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
  const ids = task.paper_ids.join(',');
  const load = useCallback((signal: AbortSignal) => Promise.all(ids.split(',').filter(Boolean).map((id) => api.paper(id, signal))), [ids]);
  const resource = useResource(load);
  return <section className="content-panel input-panel"><h2>研究输入</h2>
    {task.question && <p className="research-question">{task.question}</p>}
    <h3>选定论文 <span>{task.paper_ids.length} 篇</span></h3>
    {resource.error && <ErrorNotice error={resource.error} title="论文信息查询失败" retry={resource.reload} />}
    {resource.loading ? <Skeleton active title={false} paragraph={{ rows: 2 }} /> : <ul className="source-papers">{resource.data?.map((paper) => <li key={paper.id}><a href={paperFileUrl(paper.id)} target="_blank" rel="noopener noreferrer">{paper.title}</a><span>查看 PDF</span></li>)}</ul>}
    <p className="section-footnote">预算：{task.budget.max_steps} 步 · {task.budget.max_tokens.toLocaleString()} Token · {task.budget.timeout_seconds} 秒执行超时</p>
  </section>;
}

function TaskDetail({ taskId }: { taskId: string }) {
  const state = useTask(taskId);
  const task = state.task;
  return <>
    <Link to="/tasks" className="back-link"><ArrowLeftOutlined /> 返回任务列表</Link>
    <PageHeader title={task ? taskTypeLabels[task.task_type] : '任务详情'} description="查看任务状态、资料来源与已保存的研究结果。" action={<div className="detail-actions">{task && isTerminal(task.status) && <Link to={`/tasks/new?from_task=${task.id}`}><Button>重新创建任务</Button></Link>}<Button icon={<ReloadOutlined />} onClick={state.refresh} loading={state.refreshing}>刷新</Button></div>} />
    {state.queryError && <ErrorNotice error={state.queryError} retry={state.refresh} title={task ? '查询失败，保留上次成功查询的任务状态' : '任务查询失败'} />}
    {!task ? state.loading && <section className="content-panel"><Skeleton active paragraph={{ rows: 6 }} /></section> : <>
      <section className="task-overview" aria-label="任务状态"><div className="task-overview-main"><StatusBadge status={task.status} />{task.is_mock && <MockTag />}<span className="task-stage">{stageLabels[task.stage] || task.stage}</span></div><div className="task-overview-meta"><span>创建于 {dateTime(task.created_at)}</span><span className="identifier">{task.id}</span></div></section>
      {task.is_mock && <Alert className="inline-alert" type="warning" showIcon title="模拟运行与模拟结果" description="尚未解析或分析论文，未调用模型。以下内容用于验证流程，不应作为研究结论或模型效果指标。" />}
      {task.status === 'failed' && task.error && <Alert type="error" showIcon className="inline-alert" title={`任务执行失败 · ${task.error.code}`} description={<>{task.error.message}。可重新创建任务，原任务记录会保留。</>} />}
      <div className="detail-layout"><div className="detail-main">
        <section className="content-panel result-panel">
          {task.status === 'succeeded' ? <>
            {state.artifactError ? <ErrorNotice error={state.artifactError} title="结果查询失败，任务仍为已完成" retry={state.refresh} /> : state.artifacts === undefined ? <Skeleton active paragraph={{ rows: 5 }} /> : state.artifacts.length ? <Suspense fallback={<Spin><div className="loading-placeholder" /></Spin>}>{state.artifacts.map((artifact) => <ArtifactView key={artifact.id} artifact={artifact} />)}</Suspense> : <Alert type="warning" showIcon title="尚未取得任务产物，请重试查询。" action={<Button onClick={state.refresh}>重试查询</Button>} />}
          </> : <><div className="panel-heading"><h2>研究结果</h2></div><div className="waiting-result"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={task.status === 'queued' ? '任务正在等待执行' : task.status === 'running' ? '任务执行中，结果尚未生成' : '此任务没有生成研究结果'} /><p>{task.status === 'queued' ? '请确认对应的后端 Worker 已启动。排队期间可以离开页面，稍后按任务 ID 恢复查询。' : task.status === 'running' ? '页面会在每次查询完成后等待 2 秒再刷新，执行记录持续保存在后端。' : '请查看失败原因，调整输入或预算后重新创建任务。'}</p></div></>}
        </section>
        <TaskInputs task={task} />
      </div><aside className="detail-aside">
        <section className="content-panel trace-panel"><div className="panel-heading"><h2>执行记录</h2><span>{state.events.length} 条</span></div>
          {state.eventError && <ErrorNotice error={state.eventError} title="执行记录查询失败" retry={state.refresh} />}
          {state.events.length ? <Timeline items={state.events.map((event) => ({ key: event.seq, color: event.event_type === 'error' ? 'red' : event.status === 'succeeded' ? 'green' : 'blue', content: <div className="trace-event"><span>{dateTime(event.created_at)} · #{event.seq}</span><p>{event.message}</p></div> }))} /> : <p className="muted">尚未取得执行记录。</p>}
        </section>
        <section className="content-panel stats-panel"><h2>实际运行统计</h2><dl><div><dt>排队耗时</dt><dd>{duration(task.stats.queue_ms)}</dd></div><div><dt>执行耗时</dt><dd>{duration(task.stats.execution_ms)}</dd></div><div><dt>总耗时</dt><dd>{duration(task.stats.end_to_end_ms)}</dd></div><div><dt>输入 / 输出 Token</dt><dd>{task.stats.input_tokens ?? '—'} / {task.stats.output_tokens ?? '—'}</dd></div><div><dt>模型 / 工具调用</dt><dd>{task.stats.model_calls ?? '—'} / {task.stats.tool_calls ?? '—'}</dd></div></dl><p className="section-footnote">“—”表示没有报告或未发生测量，不等同于 0。</p><div className="version-note">工作流：{task.versions.workflow_version}<br />模型：{task.versions.model_id || (task.is_mock ? '未调用模型' : '未报告')}</div></section>
      </aside></div>
    </>}
  </>;
}

export default function TaskDetailPage() {
  const { taskId = '' } = useParams();
  return <TaskDetail key={taskId} taskId={taskId} />;
}
