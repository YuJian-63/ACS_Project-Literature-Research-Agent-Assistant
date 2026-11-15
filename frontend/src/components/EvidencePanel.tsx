import { Button, Drawer, Empty, Tabs } from 'antd';
import { ArrowRightOutlined, FilePdfOutlined, LeftOutlined, RightOutlined, SelectOutlined } from '@ant-design/icons';
import { t, useLocale } from '../i18n';
import { paperFileUrl } from '../api/client';
import type { Citation, Paper } from '../api/types';
import { useCompactViewport } from '../hooks/useCompactViewport';

interface Props {
  citations: Citation[];
  papers: Paper[];
  selectedKey?: string;
  tab: string;
  onTabChange: (tab: string) => void;
  open: boolean;
  onClose: () => void;
  onSelect: (key: string) => void;
  onReturn: () => void;
}

export default function EvidencePanel({ citations, papers, selectedKey, tab, onTabChange, open, onClose, onSelect, onReturn }: Props) {
  useLocale();
  const compact = useCompactViewport();
  const index = Math.max(0, citations.findIndex((citation) => citation.citation_key === selectedKey));
  const selected = citations[index];
  const sourcePapers = papers.length ? papers.map((paper) => ({ id: paper.id, title: paper.title })) : [...new Map(citations.map((citation) => [citation.paper_id, { id: citation.paper_id, title: citation.paper_title }])).values()];
  const content = <><Tabs activeKey={tab} onChange={onTabChange} size="small" items={[{ key: 'current', label: t('当前引用'), children: selected ? <>
    <div className="evidence-location"><span className="citation-chip">[{selected.citation_key}]</span><span>{t('来源片段')}</span><div className="evidence-pager"><Button type="text" size="small" icon={<LeftOutlined />} disabled={index === 0} aria-label={t('上一条引用')} onClick={() => onSelect(citations[index - 1].citation_key)} /><span>{index + 1} / {citations.length}</span><Button type="text" size="small" icon={<RightOutlined />} disabled={index === citations.length - 1} aria-label={t('下一条引用')} onClick={() => onSelect(citations[index + 1].citation_key)} /></div></div>
    <h3 className="evidence-paper-title">{selected.paper_title}</h3><div className="evidence-source-meta"><span>PDF</span>{t('第 {0} 页', [selected.page_number])}</div>
    <blockquote className="evidence-quote">{selected.quote}</blockquote>
    <a className="evidence-pdf-link" href={paperFileUrl(selected.paper_id, selected.page_number)} target="_blank" rel="noopener noreferrer"><FilePdfOutlined />{t('打开 PDF 对应页')}<SelectOutlined /></a>
    <div className="evidence-explainer"><h4>{t('让每个判断都有来处')}</h4><p>{t('核对原文片段、页码与上下文，再判断研究结论是否成立。')}</p></div>
    <button className="evidence-return" onClick={onReturn}>{t('返回引用位置')}<ArrowRightOutlined /></button>
  </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('此结果没有可展示的来源引用。')} /> }, { key: 'papers', label: t('输入论文 · {0}', [sourcePapers.length]), children: <ul className="evidence-papers">{sourcePapers.map((paper) => <li key={paper.id}><a href={paperFileUrl(paper.id)} target="_blank" rel="noopener noreferrer"><FilePdfOutlined /><span>{paper.title}</span></a><span>{t('查看 PDF')}</span></li>)}{!sourcePapers.length && <li>{t('暂无可展示的论文信息。')}</li>}</ul> }]} /></>;
  if (compact) return <Drawer className="evidence-drawer" title={t('证据与来源')} open={open} onClose={onClose} focusable={{ focusTriggerAfterClose: false }} size="default" styles={{ wrapper: { width: 'min(370px, calc(100vw - 20px))' } }} afterOpenChange={(visible) => { if (!visible) onReturn(); }}>{content}</Drawer>;
  return <aside className="evidence-panel" aria-label={t('证据与来源')}><h2>{t('证据与来源')}</h2>{content}</aside>;
}
