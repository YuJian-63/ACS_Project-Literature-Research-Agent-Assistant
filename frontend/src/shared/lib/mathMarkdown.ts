/** Adapt common LaTeX delimiters to the dollar syntax understood by remark-math. */
export function normalizeMathMarkdown(source: string): string {
  const lines = source.split('\n');
  const output: string[] = [];
  let plain: string[] = [];
  let fence: { marker: string; length: number } | undefined;
  const flush = () => {
    if (plain.length) {
      const displayBlocks = plain.join('\n')
        .replace(/^([ \t]*)\\\[[ \t]*\n([\s\S]*?)\n[ \t]*\\\][ \t]*$/gm,
          (_match, indent: string, body: string) => `${indent}$$\n${body}\n${indent}$$`)
        .replace(/^([ \t]*)\\\[([^\n]*?)\\\][ \t]*$/gm,
          (_match, indent: string, body: string) => `${indent}$$\n${indent}${body}\n${indent}$$`);
      output.push(displayBlocks.replace(/(`+[^`]*`+)|(?<!\\)\\\[([^\n]*?)\\\]|(?<!\\)\\\(([^\n]*?)\\\)/g,
        (match, code: string | undefined, display: string | undefined, inline: string | undefined) =>
          code ? match : `$${display ?? inline}$`));
    }
    plain = [];
  };
  for (const line of lines) {
    const opening = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (fence) {
      output.push(line);
      const closing = new RegExp(`^ {0,3}${fence.marker}{${fence.length},}\\s*$`);
      if (closing.test(line)) fence = undefined;
    } else if (opening) {
      flush();
      fence = { marker: opening[1][0], length: opening[1].length };
      output.push(line);
    } else {
      plain.push(line);
    }
  }
  flush();
  return output.join('\n');
}
