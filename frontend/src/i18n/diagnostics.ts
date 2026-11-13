import { english } from './messages';
import { getLocale, t } from './store';
import { stageLabels } from '../lib/format';
import type { ResourceError, TaskEvent } from '../api/types';

const errorMessages: Record<string, string> = {
  ARXIV_TIMEOUT: 'The arXiv request timed out. Please try again.',
  ARXIV_RATE_LIMITED: 'arXiv requests are temporarily rate limited. Please wait before retrying.',
  ARXIV_NOT_CONFIGURED: 'arXiv is not configured on the server.',
  ARXIV_UNAVAILABLE: 'arXiv is temporarily unavailable.',
  ARXIV_INVALID_RESPONSE: 'arXiv returned an invalid response.',
  ARXIV_NOT_FOUND: 'This paper could not be found on arXiv.',
  ARXIV_VERSION_MISMATCH: 'The downloaded paper does not match the requested version.',
  INVALID_AGENT_RESULT: 'The model result failed evidence validation.',
  AGENT_EXECUTION_FAILED: 'The research task could not be completed.',
  BUDGET_EXCEEDED: 'The task exceeded its execution budget.',
  TASK_TIMEOUT: 'The task exceeded its execution timeout.',
  WORKER_LOST: 'The research worker stopped responding.',
  PDF_INVALID: 'This PDF could not be read.',
  INVALID_PDF: 'Choose a valid PDF file.',
  PDF_ENCRYPTED: 'Encrypted PDFs are not supported.',
  PDF_NO_TEXT: 'No extractable text was found in this PDF.',
  PDF_LIMIT_EXCEEDED: 'This PDF exceeds the parsing limits.',
  PDF_PARSE_TIMEOUT: 'PDF parsing timed out.',
  PDF_SOURCE_CHANGED: 'The PDF changed during parsing. Upload it again.',
  PARSER_LOST: 'The parsing worker stopped responding.',
  PDF_PARSE_FAILED: 'PDF parsing failed. Upload the file again to retry.',
  IMPORT_TIMEOUT: 'The paper import timed out.',
  IMPORT_RETRY_CONFLICT: 'This import has already changed. Refresh its status before retrying.',
  IMPORT_NOT_RETRYABLE: 'This import cannot be retried in its current state.',
  PAPER_IMPORT_NOT_FOUND: 'The import record was not found.',
  PAPER_NOT_READY: 'The selected paper is not ready for research.',
  PAPER_SOURCE_CHANGED: 'A selected source has changed. Create a new task.',
  PAPER_NOT_FOUND: 'The paper was not found.',
  TASK_NOT_FOUND: 'The task was not found.',
  RUNNER_NOT_CONFIGURED: 'The research runner is not configured on the server.',
  SERVICE_NOT_READY: 'The service is not ready yet.',
  INTERNAL_ERROR: 'The server could not complete this request.',
  STORAGE_WRITE_FAILED: 'The server could not save the file.',
  FILE_UNAVAILABLE: 'The file is unavailable.',
  FILE_TOO_LARGE: 'The file exceeds the upload size limit.',
  INVALID_REQUEST: 'The request contains invalid input.',
  IDEMPOTENCY_CONFLICT: 'This submission key was already used with different input.',
  WORKFLOW_NOT_AVAILABLE: 'The selected workflow is not available.',
  NETWORK_ERROR: 'The backend is unreachable or the request timed out. Please try again.',
  CLIENT_ERROR: 'The request did not complete. Please try again.',
};

export function errorText(error: Pick<ResourceError, 'code' | 'message'>): string {
  if (getLocale() === 'zh-CN') return t(error.message);
  const httpStatus = error.message.match(/^请求未成功（HTTP (\d+)），请重试。$/)?.[1];
  if (httpStatus) return t('请求未成功（HTTP {0}），请重试。', [httpStatus]);
  const suffix = '；模型因生成长度限制而结束';
  const base = error.message.replace(suffix, '');
  if (Object.hasOwn(english, base)) {
    const translated = t(base) + (error.message.includes(suffix) ? t(suffix) : '');
    return /[.!?]$/.test(translated) ? translated : translated + '.';
  }
  if (!/[\u3400-\u9fff]/.test(error.message)) return t(error.message);
  return errorMessages[error.code] ?? `The request failed (${error.code}). Please try again.`;
}

export function eventText(event: TaskEvent): string {
  if (getLocale() === 'zh-CN') return event.message;
  if (Object.hasOwn(english, event.message)) return t(event.message);
  if (!/[\u3400-\u9fff]/.test(event.message)) return event.message;
  return stageLabels()[event.stage] ?? t('任务执行已结束');
}
