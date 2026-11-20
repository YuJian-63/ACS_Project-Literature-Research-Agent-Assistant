import { t, useLocale } from '../../../i18n';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BookOutlined } from '@ant-design/icons';
import { MockTag } from '../../../shared/components/MockTag';
import ComparisonView from './ComparisonView';
import EvidencePanel from './EvidencePanel';
import type { Artifact, Paper } from '../../../api/types';
import { citationLinks } from '../lib/citationLinks';
import { useCompactViewport } from '../../../shared/hooks/useCompactViewport';
import { useSearchParams } from 'react-router-dom';

export default function ArtifactView({ artifact, papers = [], view = 'read' }: { artifact: Artifact; papers?: Paper[]; view?: 'read' | 'compare' }) {
  useLocale();
  const compact = useCompactViewport();
  const [parameters] = useSearchParams();
  const restoring = parameters.get('artifact_id') === artifact.id;
  const [selectedKey, setSelectedKey] = useState(() => artifact.citations.find((citation) => restoring && citation.citation_key === parameters.get('citation'))?.citation_key ?? artifact.citations[0]?.citation_key);
  const [open, setOpen] = useState(() => compact && restoring && parameters.get('show_evidence') === '1');
  const [evidenceTab, setEvidenceTab] = useState('current');
  const [outline, setOutline] = useState<{ id: string; title: string }[]>([]);
  const manuscript = useRef<HTMLDivElement>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);
  const keys = useMemo(() => artifact.citations.map((citation) => citation.citation_key), [artifact.citations]);
  const plugins = useMemo(() => [remarkGfm, [citationLinks, { keys }]] as Parameters<typeof ReactMarkdown>[0]['remarkPlugins'], [keys]);
  useEffect(() => { if (!compact) setOpen(false); }, [compact]);
  useEffect(() => {
    if (view !== 'read' || !manuscript.current) return;
    setOutline([...manuscript.current.querySelectorAll('h1, h2, h3')].map((heading, index) => {
      const id = 'section-' + artifact.id + '-' + index;
      heading.id = id;
      return { id, title: heading.textContent ?? '' };
    }));
  }, [artifact.id, artifact.content_markdown, view]);
  const select = useCallback((key: string, trigger?: HTMLElement) => {
    setSelectedKey(key);
    setEvidenceTab('current');
    if (trigger) lastTrigger.current = trigger;
    if (compact) setOpen(true);
  }, [compact]);
  const markdownComponents = useMemo<Parameters<typeof ReactMarkdown>[0]['components']>(() => ({
          img: () => null,
          a: ({ href, children }) => {
            if (!href) return <span>{children}</span>;
            const key = /^#citation-(C[1-9][0-9]*)$/.exec(href)?.[1];
            if (key && keys.includes(key)) return <button className="citation-trigger" aria-label={t('查看引用 {0}', [key])} onClick={(event) => select(key, event.currentTarget)}>{children}</button>;
            try {
              const destination = new URL(href, window.location.origin);
              if (!['http:', 'https:'].includes(destination.protocol)) return <span>{children}</span>;
            } catch { return <span>{children}</span>; }
            return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
          },
        }), [keys, select]);
  function returnToCitation() {
    setOpen(false);
    const trigger = lastTrigger.current;
    if (trigger?.isConnected) { trigger.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }); trigger.focus(); }
  }
  return <article className="artifact artifact-prose" aria-label={t('研究结果')}>
    {artifact.is_mock && <div className="artifact-heading"><MockTag /><p>{t('模拟结果不提供引用，也不代表论文结论。')}</p></div>}
    <div className="artifact-layout"><div className="artifact-main">
      {view === 'compare' && artifact.comparison_table ? <ComparisonView taskReturn={{ taskId: artifact.task_id, artifactId: artifact.id, view }} comparison={artifact.comparison_table} papers={papers} citations={artifact.citations} onSelect={select} /> : <>
        {outline.length > 0 && <nav className="result-outline" aria-label={t('正文目录')}><span>{t('本页内容')}</span>{outline.map((heading) => <a key={heading.id} href={'#' + heading.id}>{heading.title}</a>)}</nav>}
        <div className="markdown" ref={manuscript}><ReactMarkdown remarkPlugins={plugins} skipHtml components={markdownComponents}>{artifact.content_markdown}</ReactMarkdown></div>
        <div className="manuscript-footer"><BookOutlined /><span>{t('研究结论需要真实来源与证据支持')}</span></div>
      </>}
      {compact && <button className="mobile-evidence-button" onClick={(event) => { lastTrigger.current = event.currentTarget; setEvidenceTab('current'); setOpen(true); }}><BookOutlined />{t('证据与来源')}<span>{artifact.citations.length}</span></button>}
    </div><EvidencePanel citations={artifact.citations} papers={papers} selectedKey={selectedKey} taskReturn={{ taskId: artifact.task_id, artifactId: artifact.id, citationKey: selectedKey, view }} tab={evidenceTab} onTabChange={setEvidenceTab} open={open} onClose={() => setOpen(false)} onSelect={select} onReturn={returnToCitation} /></div>
  </article>;
}
