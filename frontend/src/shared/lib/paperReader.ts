import { comparisonReturnUrl, withComparisonReturn } from './comparisonReturn';
export interface ResearchReaderReturn { researchId: string; citationKey?: string }
export function paperReaderUrl(paperId: string, { page, selectedIds = [], researchReturn }: { page?: number; selectedIds?: string[]; researchReturn?: ResearchReaderReturn } = {}): string {
  const parameters = new URLSearchParams({ paper_id: paperId });
  if (page !== undefined && Number.isSafeInteger(page) && page > 0) parameters.set('pdf_page', String(page));
  [...new Set(selectedIds)].forEach(id => parameters.append('selected_paper_id', id));
  if (researchReturn) {
    parameters.set('return_research', researchReturn.researchId);
    if (researchReturn.citationKey) parameters.set('return_citation', researchReturn.citationKey);
  }
  return '/papers?' + parameters;
}
export function researchReaderReturnUrl(parameters: URLSearchParams): string | undefined {
  const id = parameters.get('return_research');
  if (!id || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) return undefined;
  const result = new URLSearchParams();
  const citation = parameters.get('return_citation');
  if (citation && citation.length <= 200) result.set('citation', citation);
  return withComparisonReturn('/tasks/' + id + (result.size ? '?' + result : ''), comparisonReturnUrl(parameters.get('return_compare')));
}
