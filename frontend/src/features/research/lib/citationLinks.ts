interface MarkdownNode {
  type: string;
  value?: string;
  url?: string;
  children?: MarkdownNode[];
}

export function citationLinks({ keys }: { keys: string[] }) {
  const known = new Set(keys);
  return (tree: MarkdownNode) => {
    function visit(node: MarkdownNode) {
      if (!node.children || ['link', 'linkReference', 'code', 'inlineCode', 'html'].includes(node.type)) return;
      node.children = node.children.flatMap((child) => {
        if (child.type !== 'text' || !child.value) { visit(child); return [child]; }
        const parts: MarkdownNode[] = [];
        let offset = 0;
        for (const match of child.value.matchAll(/\[(C[1-9][0-9]*)\]/g)) {
          if (!known.has(match[1])) continue;
          if (match.index > offset) parts.push({ type: 'text', value: child.value.slice(offset, match.index) });
          parts.push({ type: 'link', url: '#citation-' + match[1], children: [{ type: 'text', value: match[0] }] });
          offset = match.index + match[0].length;
        }
        if (!parts.length) return [child];
        if (offset < child.value.length) parts.push({ type: 'text', value: child.value.slice(offset) });
        return parts;
      });
    }
    visit(tree);
  };
}
