import { agentResearch, type AgentResearchSummary, type AgentSource } from '../../api/agentResearch';
import { t, useLocale } from '../../i18n';
import { useCallback, useEffect, useRef, useState, type Key } from 'react';
import { notification as notificationApi, App, Button, Empty, Select, Table } from 'antd';
import type { TableColumnsType } from 'antd';
import { DownloadOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link, useNavigate } from 'react-router-dom';
import { asApiError, isCanceled } from '../../api/client';
import type { TaskStatus } from '../../api/types';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import { PageHeader } from '../../shared/components/PageHeader';
import { PaginationBar } from '../../shared/components/PaginationBar';
import { StatusBadge } from '../../shared/components/StatusBadge';
import { useResource } from '../../shared/hooks/useResource';
import { errorText } from '../../i18n/diagnostics';
import { dateTime, taskStatusLabels } from '../../shared/lib/format';
import { paperReaderUrl } from '../../shared/lib/paperReader';
import SourceImportDialog from './SourceImportDialog';
import MathText from '../../shared/components/MathText';

const columns = (onDelete: (task: AgentResearchSummary) => void, deleting: boolean, onImport: (source: AgentSource) => void): TableColumnsType<AgentResearchSummary> => [
  { title: t("研究任务"), key: 'task', render: (_value, task) => <div className="task-name"><Link to={`/tasks/${task.id}`}><MathText inline>{task.question || t("研究任务")}</MathText></Link><span className="task-identifier">{task.id.slice(0, 8)}</span></div> },
  { title: t('研究论文'), key: 'papers', width: 280, render: (_value, task) => <div className="task-paper-links">
    {task.papers.length ? task.papers.map(paper => paper.id !== null
      ? <Link key={paper.id} to={paperReaderUrl(paper.id)}><MathText inline>{paper.title}</MathText></Link>
      : <div key={paper.source_id} className="task-paper-import">
          <span><MathText inline>{paper.title}</MathText></span>
          <Button type="text" size="small" icon={<DownloadOutlined />} onClick={() => onImport(paper)}
            aria-label={t('导入并阅读《{0}》', [paper.title])} title={t('导入并阅读')} />
        </div>) : '—'}
  </div> },
  { title: t("状态"), dataIndex: 'status', width: 124, render: (status: TaskStatus) => <StatusBadge status={status} /> },
  { title: t("资料"), key: 'paperCount', width: 84, render: (_value, task) => t("{0} 篇", [task.papers.length]) },
  { title: t("创建时间"), dataIndex: 'created_at', width: 144, render: dateTime },
  { title: '', key: 'action', width: 160, render: (_value, task) => <div className="selection-actions"><Link aria-label={t("查看任务 {0}", [task.id.slice(0, 8)])} to={`/tasks/${task.id}`}>{t("查看")}</Link><Button danger type="text" disabled={deleting || task.status === 'running'} onClick={() => onDelete(task)} aria-label={t("删除研究记录 {0}", [task.id.slice(0, 8)])}>{t("删除")}</Button></div> },
];

const deletionNotifications = { placement: 'top', duration: 3, maxCount: 3, stack: false, classNames: { list: 'search-notification-list' } } as const;
export default function TasksPage() {
  useLocale();
  const navigate = useNavigate();
  const [importSource, setImportSource] = useState<AgentSource>();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<TaskStatus>();
  const load = useCallback((signal: AbortSignal) => agentResearch.list({ limit: 20, offset: (page - 1) * 20, status }, signal), [page, status]);
  const resource = useResource(load);
  const { modal, message } = App.useApp();
  const [notification, holder] = notificationApi.useNotification(deletionNotifications);
  const [selected, setSelected] = useState<Key[]>([]);
  const [deleting, setDeleting] = useState(false);
  const request = useRef<AbortController | null>(null);
  const filters = useRef({ status });
  filters.current = { status };
  useEffect(() => () => { request.current?.abort(); notification.destroy(); }, [notification]);

  async function removeTasks(ids: string[]) {
    if (request.current || !ids.length) return;
    const pending = new AbortController(); request.current = pending; setDeleting(true);
    const removed = new Set<string>(); const failures: string[] = [];
    notification.destroy('task-delete');
    try {
      for (const id of [...new Set(ids)]) {
        if (pending.signal.aborted) return;
        try { await agentResearch.remove(id, pending.signal); removed.add(id); }
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
        const pageInfo = await agentResearch.list({ status: current.status, limit: 1, offset: 0 }, pending.signal);
        if (pending.signal.aborted) return;
        if (filters.current.status === current.status) setPage((value) => Math.min(value, Math.max(1, Math.ceil(pageInfo.total / 20))));
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
    {importSource && <SourceImportDialog source={importSource} onClose={() => setImportSource(undefined)}
      onRead={id => { setImportSource(undefined); resource.reload(); navigate(paperReaderUrl(id)); }} />}
    <PageHeader title={t("研究记录")} description={t("查看和管理已经保存的研究结果。")} action={<Link to="/tasks/new"><Button type="primary" icon={<PlusOutlined />}>{t("新建任务")}</Button></Link>} />
    {import.meta.env.DEV && <div className="research-comparison-preview-entry"><div><strong>{t('论文比较界面示例')}</strong><p>{t('演示记录仅用于查看表格样式，不会提交研究或写入数据库。')}</p></div><Link to="/tasks/preview-comparison"><Button>{t('查看示例')}</Button></Link></div>}
    <section className="content-panel">
      <div className="filter-toolbar">
        <Select<TaskStatus> value={status} allowClear placeholder={t("全部状态")} aria-label={t("筛选任务状态")} onChange={(value) => { setStatus(value); setPage(1); }} options={Object.entries(taskStatusLabels()).map(([value, label]) => ({ value: value as TaskStatus, label }))} />
        <Button icon={<ReloadOutlined />} loading={resource.loading} onClick={resource.reload}>{t("刷新")}</Button>
      </div>
      {selected.length > 0 && <div className="selection-notice"><span>{t('已选择 {0} 条研究记录', [selected.length])}</span><div className="selection-actions"><Button danger disabled={deleting} loading={deleting} onClick={() => confirmDelete(selected.map(String))}>{t('删除已选研究')}</Button><Button type="link" disabled={deleting} onClick={() => setSelected([])}>{t('清空选择')}</Button></div></div>}
      {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
      <Table<AgentResearchSummary> className="research-records-table" rowKey="id" columns={columns((task) => confirmDelete([task.id]), deleting, setImportSource).map((column) => ({ ...column, align: 'left' as const }))} rowSelection={{ align: 'left', selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: setSelected, getCheckboxProps: (task) => ({ disabled: deleting || task.status === 'running', 'aria-label': t('选择研究记录 {0}', [task.id.slice(0, 8)]) }) }} dataSource={resource.data?.items || []} loading={resource.loading} pagination={false} scroll={{ x: 980 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={status ? t("没有匹配的任务") : t("还没有研究任务")}>{!status && <Link to="/tasks/new"><Button>{t("创建第一个任务")}</Button></Link>}</Empty> }} />
      {resource.data && <PaginationBar total={resource.data.total} page={page} onChange={setPage} />}
    </section>
  </>;
}
