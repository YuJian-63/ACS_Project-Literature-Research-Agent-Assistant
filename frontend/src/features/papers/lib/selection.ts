import type { Key } from 'react';
import type { Page, Paper } from '../../../api/types';

export function canSelectPaper(paper: Paper): boolean {
  return paper.status === 'uploaded' || paper.status === 'ready';
}

export function hasPendingPapers(page: Page<Paper>): boolean {
  return page.items.some((paper) => paper.status === 'uploaded' || paper.status === 'processing');
}

export function selectedPaperRows(keys: Key[], previous: Paper[], current: Paper[]): Paper[] {
  const known = new Map([...previous, ...current].map((paper) => [paper.id, paper]));
  return keys.map((key) => known.get(String(key))).filter((paper): paper is Paper => Boolean(paper));
}
