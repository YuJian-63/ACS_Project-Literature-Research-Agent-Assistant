import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { normalizeMathMarkdown } from '../lib/mathMarkdown';
import 'katex/dist/katex.min.css';

/** Research text with math, while keeping raw HTML and untrusted links inactive. */
export default function MathText({ children, className = '', inline = false }: { children: string; className?: string; inline?: boolean }) {
  const content = <ReactMarkdown
    remarkPlugins={[remarkGfm, remarkMath]}
    rehypePlugins={[[rehypeKatex, { trust: false, throwOnError: false }]]}
    skipHtml
    components={{ img: () => null, a: ({ children: label }) => <span>{label}</span>, ...(inline ? { p: ({ children: text }: { children?: React.ReactNode }) => <>{text}</> } : {}) }}
  >{normalizeMathMarkdown(children)}</ReactMarkdown>;
  return inline ? <span className={`research-math-text ${className}`}>{content}</span> : <div className={`research-math-text ${className}`}>{content}</div>;
}
