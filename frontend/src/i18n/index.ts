import { useSyncExternalStore } from 'react';
import { getLocale, subscribe } from './store';

export { getLocale, setLocale, t } from './store';
export type { Locale } from './store';

export function useLocale() {
  return useSyncExternalStore(subscribe, getLocale, getLocale);
}
