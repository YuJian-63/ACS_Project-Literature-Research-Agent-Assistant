import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Alert } from 'antd';
import type { AgentResult } from '../../../api/types';
import { t, useLocale } from '../../../i18n';
import { agentCitationUrl } from '../lib/agentV1';

const markdownComponents: Parameters<typeof ReactMarkdown>[0]['components'] = {
  img: () => null,
  a: ({ href, children }) => {
    const safe = href && agentCitationUrl(href, 1);
    return safe ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
  },
};

export default function AgentResultView({ result }: { result: AgentResult }) {
  useLocale();
  return <article className="content-panel artifact-prose">
    {result.stop_reason === 'partial' && <Alert type="warning" showIcon title={t('部分完成：仍有未解决的问题。')} />}
    <p>{t('停止原因：{0}', [result.stop_reason])}</p>
    <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>{result.answer}</ReactMarkdown></div>
    {result.comparison_table && <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>{result.comparison_table}</ReactMarkdown></div>}
    {result.unresolved.length > 0 && <section><h3>{t('未解决问题')}</h3><ul>{result.unresolved.map((item, index) => <li key={index}>{item}</li>)}</ul></section>}
    <section><h3>{t('引用与来源')}</h3>{result.citations.map((citation, index) => {
      const url = agentCitationUrl(citation.url, citation.page);
      return <details key={index}><summary>{citation.title || citation.paper_id} · {t('第 {0} 页', [citation.page])}</summary>
        <p>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{t('查看原始来源')}</a> : citation.url}</p>
        <dl><dt>chunk_id</dt><dd>{citation.chunk_id}</dd><dt>source_id</dt><dd>{citation.source_id}</dd><dt>paper_id</dt><dd>{citation.paper_id}</dd><dt>{t('版本')}</dt><dd>{citation.version ?? '—'}</dd></dl><blockquote>{citation.source_text}</blockquote>
      </details>;
    })}</section>
    {result.sources.length > 0 && <details><summary>{t('Agent 来源记录')}</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(result.sources, null, 2)}</pre></details>}
    {result.errors.length > 0 && <section><h3>{t('Agent 诊断')}</h3>{result.errors.map((error, index) => <pre key={index} style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(error, null, 2)}</pre>)}</section>}
    <section><h3>{t('实际运行统计')}</h3><p>{t('步数 / 模型调用 / 工具调用：{0} / {1} / {2}', [result.usage.agent_steps, result.usage.model_calls, result.usage.tool_calls])}</p><p>{t('输入 / 输出 / 总 Token：{0} / {1} / {2}', [result.usage.input_tokens ?? '—', result.usage.output_tokens ?? '—', result.usage.total_tokens ?? '—'])}</p><p>{t('执行秒数：{0}', [result.usage.elapsed_seconds])}</p>{!result.usage.token_usage_complete && <p>{t('Token 用量报告不完整。')}</p>}</section>
  </article>;
}
