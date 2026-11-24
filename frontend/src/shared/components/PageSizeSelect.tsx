import { useId } from 'react';
import { t, useLocale } from '../../i18n';

export function PageSizeSelect({ value, onChange }: { value: number; onChange: (size: number) => void }) {
  useLocale();
  const id = useId();
  return <div className="table-page-size">
    <label htmlFor={id}>{t('每页显示')}</label>
    <select id={id} value={value} onChange={event => onChange(Number(event.target.value))}>
      {[10, 20, 50].map(size => <option key={size} value={size}>{t('{0} 篇', [size])}</option>)}
    </select>
  </div>;
}
