import { t } from '../i18n/store';
import type { TaskCreate, TaskType } from '../api/types';

export const maxFileBytes = 20 * 1024 * 1024;

export function normalizeSubmission(taskType: TaskType, question: string | undefined, paperIds: string[]): TaskCreate {
  return {
    task_type: taskType,
    question: question?.trim() || null,
    paper_ids: [...new Set(paperIds.map((id) => id.toLowerCase()))].sort(),
    workflow_type: 'baseline',
  };
}

export function submissionSignature(body: TaskCreate): string {
  const { budget, ...input } = body;
  return JSON.stringify({
    ...input,
  });
}

export function selectionError(taskType: TaskType, count: number): string | null {
  if (taskType === 'review') return count >= 2 && count <= 20 ? null : t("综述任务需要选择 2—20 篇论文。");
  return count === 1 ? null : t("摘要和问答任务需要且只能选择 1 篇论文。");
}

export async function validatePdf(file: File): Promise<string | null> {
  if (!/\.pdf$/i.test(file.name) || !file.name.slice(0, -4).trim()) return t("请选择名称有效的 PDF 文件。");
  if (file.name.length > 255 || /[/\\\u0000-\u001f\u007f-\u009f]/.test(file.name)) return t("文件名过长，或包含路径、控制字符。");
  if (file.size > maxFileBytes) return t("文件超过 20 MiB，请选择更小的 PDF。");
  if (file.size === 0) return t("文件为空，请选择有效的 PDF。");
  const header = new TextDecoder().decode(await file.slice(0, 5).arrayBuffer());
  return header === '%PDF-' ? null : t("文件缺少 PDF 文件头，请确认文件格式。");
}
