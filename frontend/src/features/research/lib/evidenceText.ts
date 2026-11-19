/** Readable excerpts only; the saved verbatim quote remains available for verification. */
export function readableEvidence(quote: string): { text: string | null; trimmed: boolean } {
  const normalized = quote
    .replace(/\u00ad\s*\r?\n\s*/g, '')
    .replace(/\u00ad/g, '')
    .replace(/([-‐])\s*\r?\n\s*/g, '$1')
    .replace(/([\p{Script=Han}])\s*\r?\n\s*(?=[\p{Script=Han}])/gu, '$1')
    .replace(/\s+/g, ' ').trim();
  const sentences = [...new Intl.Segmenter(undefined, { granularity: 'sentence' }).segment(normalized)]
    .map(({ segment }) => segment.trim()).filter(Boolean);
  const complete = sentences.filter((sentence) =>
    /^[\p{Lu}\p{Lt}\p{N}\p{Script=Han}“‘"'（(\[]/u.test(sentence) &&
    /[.!?。！？][”’"')\]）]*$/u.test(sentence) &&
    !/^(?:Fig|Eq|Sec|Dr|Mr|Ms|Prof)\.$/i.test(sentence));
  return { text: complete.length ? complete.join(' ') : null, trimmed: complete.length !== sentences.length };
}
