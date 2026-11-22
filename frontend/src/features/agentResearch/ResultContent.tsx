import type { TaskMetrics } from '../../api/taskMetrics';
import { t, useLocale } from '../../i18n';
import { useState, type ReactNode } from 'react';
import { Button, Drawer, Empty, Tabs } from 'antd';
import { ArrowRightOutlined, BookOutlined, ExperimentOutlined, FileTextOutlined, LinkOutlined, QuestionCircleOutlined, TableOutlined } from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import type { AgentEvidence, AgentResult, AgentSource } from '../../api/agentResearch';
import { readableEvidence } from './lib/evidenceText';
import EvaluationPanel from './EvaluationPanel';
import RunTimeline from './RunTimeline';
import MathText from '../../shared/components/MathText';
import { normalizeMathMarkdown } from '../../shared/lib/mathMarkdown';
import './research.css';

export default function ResultContent({ result, metrics, onReadEvidence, onReadSource }: { result: AgentResult; metrics?: TaskMetrics; onReadEvidence?: (evidence: AgentEvidence) => void; onReadSource?: (source: AgentSource) => void }) {
  useLocale();
  const [parameters] = useSearchParams();
  const [selectedKey, setSelectedKey] = useState<string | undefined>(() => parameters.get('citation') || undefined);
  const [activeTab, setActiveTab] = useState('');
  const selected = result.citations.find(citation => citation.chunk_id === selectedKey);
  const byId = new Map(result.citations.map((citation, index) => [citation.chunk_id, { citation, number: index + 1 }]));
  function markdown(value: string, className = '') {
    const content = value.replace(/(?<!\\)\[([^\]\n]+)\]/g, (marker, id: string) => byId.has(id) ? `[[C${byId.get(id)!.number}]](#evidence-${encodeURIComponent(id)})` : marker);
    return <div className={`markdown research-markdown ${className}`}><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, { trust: false, throwOnError: false }]]} skipHtml components={{ img: () => null, a: ({ href, children }) => {
      if (href?.startsWith('#evidence-')) {
        let id: string;
        try { id = decodeURIComponent(href.slice(10)); } catch { return <span>{children}</span>; }
        return byId.has(id) ? <button type="button" className="citation-trigger" onClick={() => setSelectedKey(id)}>{children}</button> : <span>{children}</span>;
      }
      return href && /^https?:\/\//i.test(href) ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
    } }}>{normalizeMathMarkdown(content)}</ReactMarkdown></div>;
  }
  const entries: { key: string; label: string; icon: ReactNode; children: ReactNode }[] = [];
  if (result.answer.trim()) entries.push({ key: 'answer', label: t('研究正文'), icon: <FileTextOutlined aria-hidden />, children: markdown(result.answer) });
  if (result.comparison_table.trim()) entries.push({ key: 'comparison', label: t('论文比较'), icon: <TableOutlined aria-hidden />, children: markdown(result.comparison_table, 'research-comparison') });
  if (result.unresolved.length) entries.push({ key: 'unresolved', label: t('待解决问题'), icon: <QuestionCircleOutlined aria-hidden />, children: <section className="research-unresolved">
    <div className="research-unresolved-heading"><div><span className="research-section-label">OPEN QUESTIONS</span><h2>{t('仍需进一步确认')}</h2><p>{t('以下内容尚未得到充分确认，请结合研究正文和原文证据阅读。')}</p></div><div className="research-unresolved-count"><strong>{String(result.unresolved.length).padStart(2, '0')}</strong><span>{t('项待确认')}</span></div></div>
    <ol>{result.unresolved.map((item, index) => <li key={index}><span className="research-unresolved-number" aria-hidden>{String(index + 1).padStart(2, '0')}</span><MathText>{item}</MathText></li>)}</ol>
  </section> });
  if (result.citations.length || result.sources.length) entries.push({ key: 'sources', label: t('引用与来源'), icon: <LinkOutlined aria-hidden />, children: <div className="research-sources-view">{result.citations.length > 0 && <><h2>{t('原文证据')}</h2>{result.citations.map((citation, index) => <button type="button" className="research-citation-card" key={citation.chunk_id} onClick={() => setSelectedKey(citation.chunk_id)}><span className="citation-chip">[C{index + 1}]</span><div><strong><MathText inline>{citation.title}</MathText></strong><MathText className="research-citation-excerpt">{readableEvidence(citation.source_text).text || citation.source_text || t('请打开 PDF 查看完整上下文。')}</MathText><small>{t('PDF 第 {0} 页 · 查看证据', [citation.page])} <ArrowRightOutlined aria-hidden /></small></div></button>)}</>}{result.sources.length > 0 && <><h2>{t('研究来源')}</h2><ul className="research-source-list">{result.sources.map(source => <li key={source.source_id}><BookOutlined aria-hidden /><span><button type="button" className="research-source-link" disabled={!onReadSource} onClick={() => onReadSource?.(source)}><MathText inline>{source.title}</MathText></button>{source.version && <small>{source.version}</small>}</span></li>)}</ul></>}</div> });
  entries.push({ key: 'execution', label: t('运行记录'), icon: <FileTextOutlined aria-hidden />, children: <RunTimeline result={result} /> });
  entries.push({ key: 'evaluation', label: t('研究评估'), icon: <ExperimentOutlined aria-hidden />, children: <EvaluationPanel metrics={metrics} /> });
  return <>
    {entries.length ? <Tabs destroyOnHidden className="result-tabs research-result-tabs" activeKey={entries.some(entry => entry.key === activeTab) ? activeTab : entries[0].key} onChange={setActiveTab} items={entries} /> : <Empty description={t('本次尚未返回可展示的内容')} />}
    <Drawer open={Boolean(selected)} onClose={() => setSelectedKey(undefined)} title={t('证据与来源')} size="default" styles={{ wrapper: { width: 'min(560px, calc(100vw - 24px))' } }}>
      {selected && <><div className="evidence-location"><span className="citation-chip">[C{byId.get(selected.chunk_id)?.number}]</span><span>{t('原文片段')}</span></div><h3 className="evidence-paper-title"><MathText inline>{selected.title}</MathText></h3><div className="evidence-source-meta">{t('PDF 第 {0} 页', [selected.page])}{selected.version && ' · ' + selected.version}</div><blockquote className="evidence-quote"><MathText>{readableEvidence(selected.source_text).text || selected.source_text || t('当前摘录没有可确认的完整句子，请打开 PDF 查看上下文。')}</MathText></blockquote><Button block disabled={!onReadEvidence} icon={<BookOutlined aria-hidden />} onClick={() => onReadEvidence?.(selected)}>{t('查看 PDF 对应页')}</Button></>}
    </Drawer>
  </>;
}
