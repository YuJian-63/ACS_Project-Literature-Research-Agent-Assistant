import { errorText } from '../i18n/diagnostics';
import { t, useLocale } from '../i18n';
import { Alert, Button, Pagination, Tag } from 'antd';
import type { ReactNode } from 'react';
import type { ApiError } from '../api/client';
import type { PaperStatus, TaskStatus } from '../api/types';
import { paperStatusLabels, taskStatusLabels } from '../lib/format';

export function PageHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  useLocale();
  return <div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{action && <div className="page-actions">{action}</div>}</div>;
}

export function ErrorNotice({ error, retry, title = t("查询失败") }: { error: ApiError; retry?: () => void; title?: string }) {
  useLocale();
  return <Alert className="error-notice" type="error" showIcon title={title}
    description={<><p>{errorText(error)}</p>{error.requestId && <small>{t("请求编号：")}<span className="identifier">{error.requestId}</span></small>}</>}
    action={retry && <Button onClick={retry}>{t("重试查询")}</Button>} />;
}

export function StatusBadge({ status, kind = 'task' }: { status: TaskStatus | PaperStatus; kind?: 'task' | 'paper' }) {
  useLocale();
  const labels = kind === 'paper' ? paperStatusLabels() : taskStatusLabels();
  const text = (labels as Record<string, string>)[status] || status;
  return <span className={`status-badge status-${status}`}><span aria-hidden="true" className="status-dot" />{text}</span>;
}

export function MockTag() {
  useLocale();
  return <Tag color="gold" className="mock-tag">{t("模拟运行")}</Tag>;
}

export function PaginationBar({ total, page, onChange }: { total: number; page: number; onChange: (page: number) => void }) {
  useLocale();
  return <div className="pagination-bar"><span>{t("共 {0} 项", [total])}</span><Pagination current={page} pageSize={20} total={total} onChange={onChange} showSizeChanger={false} responsive /></div>;
}
