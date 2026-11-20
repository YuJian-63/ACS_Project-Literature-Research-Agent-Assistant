import type { PaperImport } from '../../../api/types';

export function importFeedback(previous: PaperImport | undefined, item: PaperImport, initiated = false): 'failed' | 'downloaded' | 'parse-failed' | null {
  if (!previous && !initiated) return null;
  const newAttempt = previous?.attempt !== item.attempt;
  if (item.status === 'failed' && (newAttempt || previous?.status !== 'failed')) return 'failed';
  if (item.paper_status === 'failed' && (newAttempt || previous?.paper_status !== 'failed')) return 'parse-failed';
  if (item.status === 'succeeded' && (newAttempt || previous?.status !== 'succeeded')) return 'downloaded';
  return null;
}
