import { useState } from 'react';
import { t, useLocale } from '../../../i18n';
import { paperFileUrl } from '../../../api/client';
import type { Citation, ComparisonTable, Paper } from '../../../api/types';

interface Props {
  comparison: ComparisonTable;
  papers: Paper[];
  citations: Citation[];
  onSelect: (key: string, trigger: HTMLElement) => void;
}

export default function ComparisonView({ comparison, papers, citations, onSelect }: Props) {
  useLocale();
  const [paperId, setPaperId] = useState(comparison.rows[0]?.paper_id ?? '');
  const [selectedCell, setSelectedCell] = useState('');
  const titles = new Map([...citations.map((citation) => [citation.paper_id, citation.paper_title] as const), ...papers.map((paper) => [paper.id, paper.title] as const)]);
  const known = new Set(citations.map((citation) => citation.citation_key));
  const row = comparison.rows.find((item) => item.paper_id === paperId) ?? comparison.rows[0];
  function cells(item: ComparisonTable['rows'][number], column: ComparisonTable['columns'][number]) {
    const cell = item.cells[column.key];
    if (cell?.value == null) return <span className="muted">{t('当前证据未覆盖')}</span>;
    const keys = cell.citation_keys.filter((key) => known.has(key));
    const id = item.paper_id + ':' + column.key;
    return keys.length ? <><button className="comparison-cell-trigger" aria-pressed={selectedCell === id} onClick={(event) => { setSelectedCell(id); onSelect(keys[0], event.currentTarget); }}><span>{cell.value}</span><small>[{keys[0]}] {t('查看证据')}</small></button>{keys.slice(1).map((key) => <button key={key} className="citation-trigger" onClick={(event) => { setSelectedCell(id); onSelect(key, event.currentTarget); }} aria-label={t('查看引用 {0}', [key])}>[{key}]</button>)}</> : <span>{cell.value}</span>;
  }
  return <section className="comparison-section" aria-label={t('跨论文比较')}>
    <div className="comparison-intro"><h2>{t('把差异放在同一张表里')}</h2><p>{t('选择带引用的内容，查看对应论文、页码与原文证据。')}</p></div>
    <div className="comparison-scroll" tabIndex={0} role="region" aria-label={t('跨论文比较表，可横向滚动')}><table><thead><tr><th scope="col">{t('论文')}</th>{comparison.columns.map((column) => <th scope="col" key={column.key}>{t(column.label)}</th>)}</tr></thead><tbody>{comparison.rows.map((item, index) => <tr key={item.paper_id}><th scope="row"><a href={paperFileUrl(item.paper_id)} target="_blank" rel="noopener noreferrer">{titles.get(item.paper_id) ?? t('论文 {0}', [index + 1])}</a></th>{comparison.columns.map((column) => <td key={column.key}>{cells(item, column)}</td>)}</tr>)}</tbody></table></div>
    <div className="mobile-comparison"><label htmlFor="comparison-paper">{t('选择要查看的论文')}</label><select id="comparison-paper" value={row?.paper_id ?? ''} onChange={(event) => setPaperId(event.target.value)}>{comparison.rows.map((item, index) => <option key={item.paper_id} value={item.paper_id}>{titles.get(item.paper_id) ?? t('论文 {0}', [index + 1])}</option>)}</select>{row && <><h3>{titles.get(row.paper_id) ?? t('论文')}</h3>{comparison.columns.map((column) => <section className="mobile-comparison-dimension" key={column.key}><h4>{t(column.label)}</h4>{cells(row, column)}</section>)}</>}</div>
    {!comparison.rows.length && <p className="muted">{t('暂无可展示的比较内容。')}</p>}
    <p className="section-footnote">{t('“当前证据未覆盖”表示本次证据不足以支持该维度，不代表论文全文没有讨论。')}</p>
  </section>;
}
