import { english, englishSingular } from './messages';

export type Locale = 'zh-CN' | 'en-US';
const storageKey = 'literature-v3-ui-locale';
const listeners = new Set<() => void>();
const chinese = new Map(Object.entries(english).map(([source, translation]) => [translation, source]));

function initialLocale(): Locale {
  try {
    return localStorage.getItem(storageKey) === 'en-US' ? 'en-US' : 'zh-CN';
  } catch {
    return 'zh-CN';
  }
}

let locale = initialLocale();

export function getLocale(): Locale {
  return locale;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function setLocale(next: Locale): void {
  if ((next !== 'zh-CN' && next !== 'en-US') || next === locale) return;
  locale = next;
  try { localStorage.setItem(storageKey, next); } catch {}
  listeners.forEach((listener) => listener());
}

export function t(source: string, values: readonly unknown[] = []): string {
  const original = chinese.get(source) ?? source;
  const catalog = values[0] === 1 && Object.hasOwn(englishSingular, original) ? englishSingular : english;
  const translated = locale === 'en-US' && Object.hasOwn(catalog, original) ? catalog[original] : original;
  return translated.replace(/\{(\d+)\}/g, (placeholder, index: string) => Number(index) < values.length ? String(values[Number(index)]) : placeholder);
}
