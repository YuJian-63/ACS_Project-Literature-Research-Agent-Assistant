import { t, useLocale } from '../../i18n';
import type { PaperStatus, TaskStatus } from '../../api/types';
import { paperStatusLabels, taskStatusLabels } from '../lib/format';

export function StatusBadge({ status, stage, kind = 'task' }: { status: TaskStatus | PaperStatus; stage?: string; kind?: 'task' | 'paper' }) {
  useLocale();
  const labels = kind === 'paper' ? paperStatusLabels() : taskStatusLabels();
  const partial = kind === 'task' && status === 'succeeded' && stage === 'partial';
  const text = partial ? t('部分完成') : (labels as Record<string, string>)[status] || status;
  return <span className={`status-badge status-${partial ? 'partial' : status}`}><span aria-hidden="true" className="status-dot" />{text}</span>;
}
