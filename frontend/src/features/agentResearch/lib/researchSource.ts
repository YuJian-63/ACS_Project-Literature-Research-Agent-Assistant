import type { AgentSource } from '../../../api/agentResearch';
import type { Paper } from '../../../api/types';

const paperIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const localSourcePattern = /^local:([0-9a-f-]{36})@[0-9a-f]{64}$/i;
const arxivSourcePattern = /^arxiv:((?:[0-9]{2}(?:0[1-9]|1[0-2])\.[0-9]{4,5}|[a-z][a-z-]*(?:\.[A-Z]{2})?\/[0-9]{2}(?:0[1-9]|1[0-2])[0-9]{3}))(?:(v[1-9][0-9]*)|@([0-9a-f]{12}))?$/;

export type ArxivResearchSource = { kind: 'arxiv'; externalId: string; sha256Prefix?: string };
export type ResolvedResearchSource = { kind: 'local'; paperId: string } | ArxivResearchSource
  | { kind: 'unavailable'; reason: 'missing-version' | 'invalid-source' };

export function isPaperId(value: string): boolean { return paperIdPattern.test(value); }

export function resolveResearchSource(source: AgentSource): ResolvedResearchSource {
  const unavailable = { kind: 'unavailable', reason: 'invalid-source' } as const;
  if (source.source_id.startsWith('local:')) {
    const local = localSourcePattern.exec(source.source_id);
    return local && isPaperId(local[1]) && (source.paper_id === source.source_id || source.paper_id.toLowerCase() === local[1].toLowerCase())
      ? { kind: 'local', paperId: local[1].toLowerCase() } : unavailable;
  }
  if (!source.source_id.startsWith('arxiv:') && isPaperId(source.paper_id)) return { kind: 'local', paperId: source.paper_id.toLowerCase() };
  const arxiv = arxivSourcePattern.exec(source.source_id);
  if (!arxiv || source.paper_id !== 'arxiv:' + arxiv[1]) return unavailable;
  const hint = source.version == null ? undefined : String(source.version).replace(/^v/, '');
  if (hint !== undefined && !/^[1-9][0-9]*$/.test(hint)) return unavailable;
  if (arxiv[2] && hint !== undefined && arxiv[2] !== 'v' + hint) return unavailable;
  const version = arxiv[2] || (hint ? 'v' + hint : undefined);
  if (!version) return { kind: 'unavailable', reason: 'missing-version' };
  const resolved: ArxivResearchSource = { kind: 'arxiv', externalId: arxiv[1] + version };
  if (arxiv[3]) resolved.sha256Prefix = arxiv[3];
  return resolved;
}

export function importedPaperProblem(source: ArxivResearchSource, paper: Paper, page?: number): 'version-mismatch' | 'content-mismatch' | 'page-out-of-range' | null {
  if (!isPaperId(paper.id) || paper.source?.provider !== 'arxiv' || paper.source.external_id !== source.externalId) return 'version-mismatch';
  if (source.sha256Prefix && !paper.sha256.startsWith(source.sha256Prefix)) return 'content-mismatch';
  if (page !== undefined && (!Number.isSafeInteger(page) || page < 1 || paper.page_count === null || page > paper.page_count)) return 'page-out-of-range';
  return null;
}
