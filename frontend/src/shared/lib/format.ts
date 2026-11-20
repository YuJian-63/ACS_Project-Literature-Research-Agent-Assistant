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
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

export function duration(milliseconds: number | null): string {
  if (milliseconds === null) return '—';
  return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(1)} s`;
}

export function isTerminal(status: TaskStatus): boolean {
  return status === 'succeeded' || status === 'failed';
}
