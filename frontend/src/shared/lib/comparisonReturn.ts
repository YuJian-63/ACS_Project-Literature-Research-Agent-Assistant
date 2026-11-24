const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const sections = ['answer', 'comparison', 'unresolved', 'sources', 'evaluation', 'execution'];
export function comparisonReturnUrl(value: string | null): string | undefined {
  if (!value || !value.startsWith('/tasks/compare?')) return undefined;
  const query = new URLSearchParams(value.slice('/tasks/compare?'.length));
  const a = query.get('a'), b = query.get('b');
  if (!a || !b || !uuid.test(a) || !uuid.test(b) || a.toLowerCase() === b.toLowerCase()) return undefined;
  const result = new URLSearchParams({ a, b });
  const section = query.get('section');
  if (section && sections.includes(section)) result.set('section', section);
  return '/tasks/compare?' + result;
}
export function withComparisonReturn(target: string, comparison?: string): string {
  const safe = comparisonReturnUrl(comparison ?? null);
  if (!safe) return target;
  const [path, query = ''] = target.split('?');
  const params = new URLSearchParams(query);
  params.set('return_compare', safe);
  return path + '?' + params;
}
