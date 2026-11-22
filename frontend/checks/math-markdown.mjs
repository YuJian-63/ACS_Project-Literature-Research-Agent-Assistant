import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { normalizeMathMarkdown } from '../src/shared/lib/mathMarkdown.ts';

const source = `- The weighted sum is:
  \\[
  \\text{Attention}(Q,K,V)=\\sum_k w_k v_k
  \\]
  which equals \\(E[v_k]\\). [C1](#evidence-one)

### Next section
The citation [C2](#evidence-two) remains a link.`;

const html = renderToStaticMarkup(createElement(ReactMarkdown, {
  remarkPlugins: [remarkGfm, remarkMath],
  rehypePlugins: [[rehypeKatex, { trust: false, throwOnError: false }]],
  children: normalizeMathMarkdown(source),
}));

assert.match(html, /class="katex-display"/);
assert.match(html, /which equals/);
assert.match(html, /<h3>Next section<\/h3>/);
assert.match(html, /href="#evidence-two"/);
assert.doesNotMatch(html, /katex-error/);
assert.doesNotMatch(html, /<p>\\text\{Attention\}/);

const singleLineDisplay = renderToStaticMarkup(createElement(ReactMarkdown, {
  remarkPlugins: [remarkMath],
  rehypePlugins: [[rehypeKatex, { trust: false, throwOnError: false }]],
  children: normalizeMathMarkdown('\\[x^2\\]'),
}));
assert.match(singleLineDisplay, /class="katex-display"/);
console.log('math markdown regression passed');
