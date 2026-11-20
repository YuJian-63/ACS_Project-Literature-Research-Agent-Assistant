import type { AgentResearchRequest } from '../../api/agentResearch';
import { createUuid } from './uuid';

export interface ResearchSubmission { fingerprint: string; key: string }
export interface ResearchDraft { question: string; paperIds: string[]; sourceKey?: string; submission?: ResearchSubmission }
const prefix = 'literature-v3-research-draft:';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function researchSubmission(input: AgentResearchRequest, previous?: ResearchSubmission): ResearchSubmission {
  const fingerprint = JSON.stringify([input.question.trim(), input.paper_ids ?? [], input.allow_search ?? true]);
  return previous?.fingerprint === fingerprint ? previous : { fingerprint, key: createUuid() };
}

export function readResearchDraft(userId: string): ResearchDraft | undefined {
  try {
    const draft = JSON.parse(sessionStorage.getItem(prefix + userId) || 'null');
    if (draft?.version !== 1 || typeof draft.question !== 'string' || draft.question.length > 8000
      || !Array.isArray(draft.paperIds) || draft.paperIds.length > 20
      || !draft.paperIds.every((id: unknown) => typeof id === 'string' && uuid.test(id))
      || new Set(draft.paperIds).size !== draft.paperIds.length) return undefined;
    const submission = typeof draft.submission?.fingerprint === 'string' && typeof draft.submission?.key === 'string' && uuid.test(draft.submission.key)
      ? { fingerprint: draft.submission.fingerprint, key: draft.submission.key } : undefined;
    return { question: draft.question, paperIds: draft.paperIds, submission,
      ...(typeof draft.sourceKey === 'string' && draft.sourceKey.length <= 2000 ? { sourceKey: draft.sourceKey } : {}) };
  } catch { return undefined; }
}

export function saveResearchDraft(userId: string, draft: ResearchDraft) {
  try {
    if (!draft.question && !draft.paperIds.length && !draft.submission) sessionStorage.removeItem(prefix + userId);
    else sessionStorage.setItem(prefix + userId, JSON.stringify({ version: 1, ...draft }));
  } catch {}
}

export function clearResearchDraft(userId: string) {
  try { sessionStorage.removeItem(prefix + userId); } catch {}
}

export function clearResearchDrafts() {
  try {
    const keys = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index));
    keys.forEach(key => { if (key?.startsWith(prefix)) sessionStorage.removeItem(key); });
  } catch {}
}
