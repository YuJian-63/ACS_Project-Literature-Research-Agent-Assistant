import { useEffect, useRef, useState } from 'react';
import { asApiError, isCanceled, type ApiError } from '../../api/client';

export function useResource<T>(load: (signal: AbortSignal) => Promise<T>, pollInterval = 0, refreshWhile?: (data: T) => boolean) {
  const [state, setState] = useState<{ data?: T; loading: boolean; error?: ApiError }>({ loading: true });
  const [revision, setRevision] = useState(0);
  const previousLoad = useRef(load);
  const previousData = useRef<T | undefined>(undefined);
  const silentRefresh = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let data: T | undefined = previousLoad.current === load && silentRefresh.current ? previousData.current : undefined;
    previousLoad.current = load;
    silentRefresh.current = false;
    previousData.current = data;
    setState({ data, loading: data === undefined });
    async function read() {
      try {
        const result = await load(controller.signal);
        if (controller.signal.aborted) return;
        data = result;
        previousData.current = result;
        setState({ data, loading: false });
      } catch (error) {
        if (!controller.signal.aborted && !isCanceled(error)) setState({ data, loading: false, error: asApiError(error) });
      } finally {
        if (!controller.signal.aborted && pollInterval > 0 && data !== undefined && refreshWhile?.(data)) timer = setTimeout(() => { void read(); }, pollInterval);
      }
    }
    void read();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [load, revision, pollInterval, refreshWhile]);
  return { ...state,
    reload: () => { silentRefresh.current = false; setRevision(value => value + 1); },
    refresh: () => { silentRefresh.current = true; setRevision(value => value + 1); },
  };
}
