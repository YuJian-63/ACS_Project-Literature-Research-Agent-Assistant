import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import type { AgentResearchRecord } from '../../api/agentResearch';
import { api } from '../../api/client';
import { useLocale } from '../../i18n';
import { useResource } from '../../shared/hooks/useResource';
import { paperReaderUrl } from '../../shared/lib/paperReader';
import { withComparisonReturn } from '../../shared/lib/comparisonReturn';
import { isPaperId, resolveResearchSource } from './lib/researchSource';
import MathText from '../../shared/components/MathText';

export default function ComparisonPaperList({ record, returnUrl }: { record: AgentResearchRecord; returnUrl: string }) {
  const locale = useLocale();
  const items = (record.result?.sources ?? []).map(source => {
    const resolved = resolveResearchSource(source);
    return { id: resolved.kind === 'local' ? resolved.paperId : '', title: source.title, key: source.source_id };
  });
  for (const id of record.paper_ids) if (!items.some(item => item.id === id)) items.push({ id, title: '', key: id });
  const signature = JSON.stringify(items);
  const load = useCallback(async (signal: AbortSignal) => {
    const entries: typeof items = JSON.parse(signature);
    return Promise.all(entries.map(async item => {
      if (!item.id || (item.title && !isPaperId(item.title))) return item;
      try { const paper = await api.paper(item.id, signal); return { ...item, title: paper.title }; }
      catch { return { ...item, title: '' }; }
    }));
  }, [signature]);
  const resource = useResource(load);
  if (!items.length) return <span className="comparison-unavailable">{locale === 'en-US' ? 'Not provided' : '未提供'}</span>;
  return <ul className="comparison-paper-items">{(resource.data ?? items).map(item => {
    const name = item.title && !isPaperId(item.title) ? item.title : `${locale === 'en-US' ? 'Paper' : '论文'} ${item.id.slice(0, 8)}`;
    return <li key={item.key}>{item.id ? <Link to={withComparisonReturn(paperReaderUrl(item.id), returnUrl)}><MathText inline>{name}</MathText></Link> : <MathText inline>{name}</MathText>}</li>;
  })}</ul>;
}
