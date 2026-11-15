import { t } from '../../../i18n/store';
import type { TaskCreate, TaskType } from '../../../api/types';

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
