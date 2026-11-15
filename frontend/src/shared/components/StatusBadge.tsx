import { useLocale } from '../../i18n';
import type { PaperStatus, TaskStatus } from '../../api/types';
import { paperStatusLabels, taskStatusLabels } from '../lib/format';

export function StatusBadge({ status, kind = 'task' }: { status: TaskStatus | PaperStatus; kind?: 'task' | 'paper' }) {
  useLocale();
  const labels = kind === 'paper' ? paperStatusLabels() : taskStatusLabels();
  const text = (labels as Record<string, string>)[status] || status;
  return <span className={`status-badge status-${status}`}><span aria-hidden="true" className="status-dot" />{text}</span>;
}
