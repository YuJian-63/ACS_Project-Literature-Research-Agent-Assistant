import { t, useLocale } from '../../../i18n';
import { useCallback, useState } from 'react';
import { Button, Empty, Select, Table } from 'antd';
import type { TableColumnsType } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { api } from '../../../api/client';
import type { TaskStatus, TaskSummary, TaskType } from '../../../api/types';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { MockTag } from '../../../shared/components/MockTag';
import { PageHeader } from '../../../shared/components/PageHeader';
import { PaginationBar } from '../../../shared/components/PaginationBar';
import { StatusBadge } from '../../../shared/components/StatusBadge';
import { useResource } from '../../../shared/hooks/useResource';
import { dateTime, taskStatusLabels, taskTypeLabels } from '../../../shared/lib/format';

const columns = (): TableColumnsType<TaskSummary> => [
  { title: t("研究任务"), key: 'task', render: (_value, task) => <div className="task-name"><Link to={`/tasks/${task.id}`}>{taskTypeLabels()[task.task_type]}</Link><span className="task-question">{task.question || t("提炼论文的研究问题、方法与主要发现")}</span><span className="task-identifier">{task.id.slice(0, 8)}</span></div> },
  { title: t("状态"), dataIndex: 'status', width: 124, render: (status: TaskStatus) => <StatusBadge status={status} /> },
  { title: t("资料"), dataIndex: 'paper_ids', width: 84, render: (ids: string[]) => t("{0} 篇", [ids.length]) },
  { title: t("执行方式"), key: 'mode', width: 120, render: (_value, task) => task.is_mock ? <MockTag /> : t("真实运行") },
  { title: t("创建时间"), dataIndex: 'created_at', width: 144, render: dateTime },
  { title: '', key: 'action', width: 72, render: (_value, task) => <Link aria-label={t("查看任务 {0}", [task.id.slice(0, 8)])} to={`/tasks/${task.id}`}>{t("查看")}</Link> },
];

export default function TasksPage() {
  useLocale();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<TaskStatus>();
  const [taskType, setTaskType] = useState<TaskType>();
  const load = useCallback((signal: AbortSignal) => api.tasks({ limit: 20, offset: (page - 1) * 20, status, task_type: taskType }, signal), [page, status, taskType]);
  const resource = useResource(load);
  return <>
    <PageHeader title={t("研究记录")} description={t("回到每一次研究，查看执行过程与已经保存的结果。")} action={<Link to="/tasks/new"><Button type="primary" icon={<PlusOutlined />}>{t("新建任务")}</Button></Link>} />
    <section className="content-panel">
      <div className="panel-heading"><div><h2>{t("任务记录")}</h2><p>{t("排队与运行状态以详情页轮询为准；重新执行会创建独立任务。")}</p></div><Button icon={<ReloadOutlined />} loading={resource.loading} onClick={resource.reload}>{t("刷新")}</Button></div>
      <div className="filter-toolbar">
        <Select<TaskStatus> value={status} allowClear placeholder={t("全部状态")} aria-label={t("筛选任务状态")} onChange={(value) => { setStatus(value); setPage(1); }} options={Object.entries(taskStatusLabels()).map(([value, label]) => ({ value: value as TaskStatus, label }))} />
        <Select<TaskType> value={taskType} allowClear placeholder={t("全部类型")} aria-label={t("筛选任务类型")} onChange={(value) => { setTaskType(value); setPage(1); }} options={Object.entries(taskTypeLabels()).map(([value, label]) => ({ value: value as TaskType, label }))} />
      </div>
      {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
      <Table<TaskSummary> rowKey="id" columns={columns()} dataSource={resource.data?.items || []} loading={resource.loading} pagination={false} scroll={{ x: 760 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={status || taskType ? t("没有匹配的任务") : t("还没有研究任务")}>{!status && !taskType && <Link to="/tasks/new"><Button>{t("创建第一个任务")}</Button></Link>}</Empty> }} />
      {resource.data && <PaginationBar total={resource.data.total} page={page} onChange={setPage} />}
    </section>
  </>;
}
