import { t, getLocale } from '../i18n/store';
import type { PaperStatus, TaskStatus, TaskType } from '../api/types';

export const taskTypeLabels = (): Record<TaskType, string> => ({ summary: t("论文摘要"), qa: t("论文问答"), review: t("跨论文综述") });
export const taskStatusLabels = (): Record<TaskStatus, string> => ({ queued: t("排队中"), running: t("运行中"), succeeded: t("已完成"), failed: t("执行失败") });
export const paperStatusLabels = (): Record<PaperStatus, string> => ({ uploaded: t("已上传"), processing: t("解析中"), ready: t("已就绪"), failed: t("解析失败") });
export const stageLabels = (): Record<string, string> => ({ analyzing: t("正在分析论文"), synthesizing: t("正在生成综述章节"), validating: t("正在校验综述与引用"), queued: t("等待 Worker 领取"), retrieving: t("读取论文证据"), generating: t("生成研究结果"), completed: t("研究任务完成"), mock_preparing: t("准备模拟流程"), mock_generating: t("生成模拟结果"), mock_completed: t("模拟流程完成"), failed: t("执行已结束") });
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
