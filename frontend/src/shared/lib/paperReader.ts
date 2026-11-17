export interface TaskReaderReturn {
  taskId: string;
  artifactId: string;
  citationKey?: string;
  view: 'read' | 'compare';
}

export function paperReaderUrl(paperId: string, { page, selectedIds = [], taskReturn }: { page?: number; selectedIds?: string[]; taskReturn?: TaskReaderReturn } = {}): string {
  const parameters = new URLSearchParams({ paper_id: paperId });
  if (page !== undefined && Number.isSafeInteger(page) && page > 0) parameters.set('pdf_page', String(page));
  [...new Set(selectedIds)].forEach((id) => parameters.append('selected_paper_id', id));
  if (taskReturn) {
    parameters.set('return_task', taskReturn.taskId);
    parameters.set('return_artifact', taskReturn.artifactId);
    parameters.set('return_view', taskReturn.view);
    if (taskReturn.citationKey) parameters.set('return_citation', taskReturn.citationKey);
  }
  return '/papers?' + parameters;
}

export function taskReaderReturnUrl(parameters: URLSearchParams): string | undefined {
  const taskId = parameters.get('return_task');
  const artifactId = parameters.get('return_artifact');
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!taskId || !artifactId || !uuid.test(taskId) || !uuid.test(artifactId)) return undefined;
  const result = new URLSearchParams({ artifact_id: artifactId, view: parameters.get('return_view') === 'compare' ? 'compare' : 'read', show_evidence: '1' });
  const citation = parameters.get('return_citation');
  if (citation && /^C[1-9][0-9]*$/.test(citation)) result.set('citation', citation);
  return '/tasks/' + taskId + '?' + result;
}
