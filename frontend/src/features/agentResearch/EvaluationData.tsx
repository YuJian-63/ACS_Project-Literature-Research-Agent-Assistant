import { useLocale } from '../../i18n';

/** Render every returned field, including future optional metadata, as escaped text. */
export function EvaluationData({ value }: { value: unknown }) {
  const locale = useLocale();
  if (value === null || value === undefined) return <span className="evaluation-empty">—</span>;
  if (typeof value === 'boolean') return <span>{locale === 'en-US' ? String(value) : value ? '是' : '否'}</span>;
  if (Array.isArray(value)) return value.length ? <ol className="evaluation-data-list">{value.map((item, index) => <li key={index}><EvaluationData value={item} /></li>)}</ol> : <span>∅</span>;
  if (typeof value === 'object') return <dl className="evaluation-data">{Object.entries(value).map(([key, item]) => <div key={key}><dt>{key}</dt><dd><EvaluationData value={item} /></dd></div>)}</dl>;
  return <span>{String(value)}</span>;
}
