import { useEffect, useState } from 'react';
import { asApiError, isCanceled, type ApiError } from '../api/client';

export function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<{ data?: T; loading: boolean; error?: ApiError }>({ loading: true });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ loading: true });
    load(controller.signal).then((data) => {
      if (!controller.signal.aborted) setState({ data, loading: false });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted && !isCanceled(error)) setState({ loading: false, error: asApiError(error) });
    });
    return () => controller.abort();
  }, [load, revision]);
  return { ...state, reload: () => setRevision((value) => value + 1) };
}
