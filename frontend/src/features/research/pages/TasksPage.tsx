import { t, useLocale } from '../../../i18n';
import { useCallback, useEffect, useRef, useState, type Key } from 'react';
import { notification as notificationApi, App, Button, Empty, Select, Table } from 'antd';
import type { TableColumnsType } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { api, asApiError, isCanceled } from '../../../api/client';
import type { TaskStatus, TaskSummary, TaskType } from '../../../api/types';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { MockTag } from '../../../shared/components/MockTag';
import { PageHeader } from '../../../shared/components/PageHeader';
import { PaginationBar } from '../../../shared/components/PaginationBar';
import { StatusBadge } from '../../../shared/components/StatusBadge';
import { useResource } from '../../../shared/hooks/useResource';
import { errorText } from '../../../i18n/diagnostics';
import { dateTime, taskStatusLabels, taskTypeLabels } from '../../../shared/lib/format';

const columns = (onDelete: (task: TaskSummary) => void, deleting: boolean): TableColumnsType<TaskSummary> => [
  { title: t("研究任务"), key: 'task', render: (_value, task) => <div className="task-name"><Link to={`/tasks/${task.id}`}>{taskTypeLabels()[task.task_type]}</Link><span className="task-question">{task.question || t("提炼论文的研究问题、方法与主要发现")}</span><span className="task-identifier">{task.id.slice(0, 8)}</span></div> },
  { title: t("状态"), dataIndex: 'status', width: 124, render: (status: TaskStatus, task) => <StatusBadge status={status} stage={task.stage} /> },
  { title: t("资料"), dataIndex: 'paper_ids', width: 84, render: (ids: string[]) => t("{0} 篇", [ids.length]) },
  { title: t("执行方式"), key: 'mode', width: 120, render: (_value, task) => task.is_mock ? <MockTag /> : t("真实运行") },
  { title: t("创建时间"), dataIndex: 'created_at', width: 144, render: dateTime },
  { title: '', key: 'action', width: 160, render: (_value, task) => <div className="selection-actions"><Link aria-label={t("查看任务 {0}", [task.id.slice(0, 8)])} to={`/tasks/${task.id}`}>{t("查看")}</Link><Button danger type="text" disabled={deleting || task.status === 'running'} onClick={() => onDelete(task)} aria-label={t("删除研究记录 {0}", [task.id.slice(0, 8)])}>{t("删除")}</Button></div> },
];

const deletionNotifications = { placement: 'top', duration: 5, maxCount: 3, stack: false, classNames: { list: 'search-notification-list' } } as const;

export default function TasksPage() {
  useLocale();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<TaskStatus>();
  const [taskType, setTaskType] = useState<TaskType>();
  const load = useCallback((signal: AbortSignal) => api.tasks({ limit: 20, offset: (page - 1) * 20, status, task_type: taskType }, signal), [page, status, taskType]);
  const resource = useResource(load);
  const { modal, message } = App.useApp();
  const [notification, holder] = notificationApi.useNotification(deletionNotifications);
  const [selected, setSelected] = useState<Key[]>([]);
  const [deleting, setDeleting] = useState(false);
  const request = useRef<AbortController | null>(null);
  const filters = useRef({ status, taskType });
  filters.current = { status, taskType };
  useEffect(() => () => { request.current?.abort(); notification.destroy(); }, [notification]);

  async function removeTasks(ids: string[]) {
    if (request.current || !ids.length) return;
    const pending = new AbortController(); request.current = pending; setDeleting(true);
    const removed = new Set<string>(); const failures: string[] = [];
    notification.destroy('task-delete');
    try {
      for (const id of [...new Set(ids)]) {
        if (pending.signal.aborted) return;
        try { await api.deleteTask(id, pending.signal); removed.add(id); }
        catch (error) {
          if (pending.signal.aborted || isCanceled(error)) return;
          const failure = asApiError(error);
          if (failure.status === 404) removed.add(id);
          else failures.push(errorText(failure));
        }
      }
      if (pending.signal.aborted) return;
      setSelected((current) => current.filter((id) => !removed.has(String(id))));
      if (failures.length) notification.error({ key: 'task-delete', className: 'search-notification', closable: true, title: t('{0} 条研究记录未删除', [failures.length]), description: <div className="search-notification-content"><ul>{[...new Set(failures)].map((reason) => <li key={reason}>{reason}</li>)}</ul></div> });
      if (removed.size) {
        void message.success(t('已删除 {0} 条研究记录', [removed.size]));
        const current = filters.current;
        const pageInfo = await api.tasks({ status: current.status, task_type: current.taskType, limit: 1, offset: 0 }, pending.signal);
        if (pending.signal.aborted) return;
        if (filters.current.status === current.status && filters.current.taskType === current.taskType) setPage((value) => Math.min(value, Math.max(1, Math.ceil(pageInfo.total / 20))));
      }
      resource.reload();
    } catch (error) {
      if (!pending.signal.aborted && !isCanceled(error)) notification.error({ key: 'task-delete', className: 'search-notification', title: t('查询失败'), description: errorText(asApiError(error)) });
      resource.reload();
    } finally { if (request.current === pending) request.current = null; if (!pending.signal.aborted) setDeleting(false); }
  }

  function confirmDelete(ids: string[]) {
    modal.confirm({ title: t('删除 {0} 条研究记录？', [ids.length]), content: t('将删除研究结果及其引用记录，但保留原论文。论文不再被其他研究引用后即可删除。正在执行的研究会保留。'), okText: t('确认删除'), cancelText: t('取消'), okButtonProps: { danger: true }, onOk: () => removeTasks(ids) });
  }
  return <>
    {holder}
    <PageHeader title={t("研究记录")} description={t("查看和管理已经保存的研究结果。")} action={<Link to="/tasks/new"><Button type="primary" icon={<PlusOutlined />}>{t("新建任务")}</Button></Link>} />
    <section className="content-panel">
      <div className="filter-toolbar">
        <Select<TaskStatus> value={status} allowClear placeholder={t("全部状态")} aria-label={t("筛选任务状态")} onChange={(value) => { setStatus(value); setPage(1); }} options={Object.entries(taskStatusLabels()).map(([value, label]) => ({ value: value as TaskStatus, label }))} />
        <Select<TaskType> value={taskType} allowClear placeholder={t("全部类型")} aria-label={t("筛选任务类型")} onChange={(value) => { setTaskType(value); setPage(1); }} options={Object.entries(taskTypeLabels()).map(([value, label]) => ({ value: value as TaskType, label }))} />
        <Button icon={<ReloadOutlined />} loading={resource.loading} onClick={resource.reload}>{t("刷新")}</Button>
      </div>
      {selected.length > 0 && <div className="selection-notice"><span>{t('已选择 {0} 条研究记录', [selected.length])}</span><div className="selection-actions"><Button danger disabled={deleting} loading={deleting} onClick={() => confirmDelete(selected.map(String))}>{t('删除已选研究')}</Button><Button type="link" disabled={deleting} onClick={() => setSelected([])}>{t('清空选择')}</Button></div></div>}
      {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
      <Table<TaskSummary> rowKey="id" columns={columns((task) => confirmDelete([task.id]), deleting)} rowSelection={{ selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: setSelected, getCheckboxProps: (task) => ({ disabled: deleting || task.status === 'running', 'aria-label': t('选择研究记录 {0}', [task.id.slice(0, 8)]) }) }} dataSource={resource.data?.items || []} loading={resource.loading} pagination={false} scroll={{ x: 760 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={status || taskType ? t("没有匹配的任务") : t("还没有研究任务")}>{!status && !taskType && <Link to="/tasks/new"><Button>{t("创建第一个任务")}</Button></Link>}</Empty> }} />
      {resource.data && <PaginationBar total={resource.data.total} page={page} onChange={setPage} />}
    </section>
  </>;
}
