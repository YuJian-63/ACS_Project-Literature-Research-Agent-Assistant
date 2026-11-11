import type { PaperStatus, TaskStatus, TaskType } from '../api/types';

export const taskTypeLabels: Record<TaskType, string> = { summary: '论文摘要', qa: '论文问答', review: '跨论文综述' };
export const taskStatusLabels: Record<TaskStatus, string> = { queued: '排队中', running: '运行中', succeeded: '已完成', failed: '执行失败' };
export const paperStatusLabels: Record<PaperStatus, string> = { uploaded: '已上传', processing: '解析中', ready: '已就绪', failed: '解析失败' };
export const stageLabels: Record<string, string> = { queued: '等待 Worker 领取', retrieving: '读取论文证据', generating: '生成研究结果', completed: '研究任务完成', mock_preparing: '准备模拟流程', mock_generating: '生成模拟结果', mock_completed: '模拟流程完成', failed: '执行已结束' };
const dateFormatter = new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

export function dateTime(value: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return dateFormatter.format(new Date(value));
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
