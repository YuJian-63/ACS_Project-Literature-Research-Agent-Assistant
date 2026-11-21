import { t, getLocale } from '../../i18n/store';
import type { PaperStatus, TaskStatus } from '../../api/types';

export const taskStatusLabels = (): Record<TaskStatus, string> => ({ queued: t("排队中"), running: t("运行中"), succeeded: t("已完成"), failed: t("执行失败") });
export const paperStatusLabels = (): Record<PaperStatus, string> => ({ uploaded: t("已上传"), processing: t("解析中"), ready: t("已就绪"), failed: t("解析失败") });
const dateOptions: Intl.DateTimeFormatOptions = { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false };

export function dateTime(value: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return new Intl.DateTimeFormat(getLocale(), dateOptions).format(new Date(value));
}

export function fileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit < 2 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

export function duration(milliseconds: number | null): string {
  if (milliseconds === null) return '—';
  return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(1)} s`;
}

export function isTerminal(status: TaskStatus): boolean {
  return status === 'succeeded' || status === 'failed';
}
