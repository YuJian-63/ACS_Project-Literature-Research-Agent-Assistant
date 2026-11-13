import { t, useLocale } from '../i18n';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { MockTag } from './Common';
import type { Artifact } from '../api/types';
import { paperFileUrl } from '../api/client';

export default function ArtifactView({ artifact }: { artifact: Artifact }) {
  useLocale();
  const comparison = artifact.comparison_table;
  return <article className="artifact" aria-label={t("研究结果")}>
    <div className="artifact-heading"><h2>{artifact.title}</h2>{artifact.is_mock && <MockTag />}</div>
    <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
      img: () => null,
      a: ({ href, children }) => {
        if (!href) return <span>{children}</span>;
        try {
          const destination = new URL(href, window.location.origin);
          if (!['http:', 'https:'].includes(destination.protocol)) return <span>{children}</span>;
        } catch { return <span>{children}</span>; }
        return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
      },
    }}>{artifact.content_markdown}</ReactMarkdown></div>
    {comparison && <section className="comparison-section"><h3>{t("跨论文比较")}</h3><div className="comparison-scroll"><table><thead><tr><th>{t("论文")}</th>{comparison.columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{comparison.rows.map((row) => <tr key={row.paper_id}><td><a href={paperFileUrl(row.paper_id)} target="_blank" rel="noopener noreferrer">{row.paper_id.slice(0, 8)}</a></td>{comparison.columns.map((column) => <td key={column.key}>{row.cells[column.key]?.value ?? <span className="muted">{t("未报告")}</span>}{row.cells[column.key]?.citation_keys.map((key) => <a key={key} href={`#citation-${key}`} className="citation-mark">[{key}]</a>)}</td>)}</tr>)}</tbody></table></div></section>}
    <section className="citations-section"><h3>{t("支持证据")} <span>{artifact.citations.length}</span></h3>{artifact.citations.length ? artifact.citations.map((citation) => <div id={`citation-${citation.citation_key}`} className="citation" key={citation.id}><a href={paperFileUrl(citation.paper_id, citation.page_number)} target="_blank" rel="noopener noreferrer">{t("[{0}] {1} · 第 {2} 页 · 查看原文", [citation.citation_key, citation.paper_title, citation.page_number])}</a><blockquote>{citation.quote}</blockquote></div>) : <p className="muted">{artifact.is_mock ? t("模拟结果不提供引用，也不代表论文结论。") : t("此结果没有可展示的来源引用。")}</p>}</section>
  </article>;
}
