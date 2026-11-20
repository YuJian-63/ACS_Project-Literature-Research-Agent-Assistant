import { useEffect, useRef, useState } from 'react';
import { api, asApiError, isCanceled, type ApiError } from '../../../api/client';
import type { Artifact, Task } from '../../../api/types';
import { isTerminal } from '../../../shared/lib/format';

export function useTask(taskId: string) {
  const [task, setTask] = useState<Task>();
  const [artifacts, setArtifacts] = useState<Artifact[]>();
  const [queryError, setQueryError] = useState<ApiError>();
  const [artifactError, setArtifactError] = useState<ApiError>();
  const [checkedAt, setCheckedAt] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [revision, setRevision] = useState(0);
  const latestTask = useRef<Task | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      setRefreshing(true);
      let stop = false;
      try {
        const result = await api.task(taskId, controller.signal);
        if (controller.signal.aborted) return;
        latestTask.current = result;
        setTask(result);
        setCheckedAt(Date.now());
        setQueryError(undefined);
        stop = isTerminal(result.status);
        if (result.status === 'succeeded') {
          try {
            const response = await api.artifacts(taskId, controller.signal);
            if (controller.signal.aborted) return;
            setArtifacts(response.items);
            setArtifactError(undefined);
          } catch (error) {
            if (!controller.signal.aborted && !isCanceled(error)) setArtifactError(asApiError(error));
          }
        }
      } catch (error) {
        if (controller.signal.aborted || isCanceled(error)) return;
        const failure = asApiError(error);
        setQueryError(failure);
        stop = failure.status === 404 || failure.status === 422 || Boolean(latestTask.current?.id === taskId && isTerminal(latestTask.current.status));
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          setRefreshing(false);
          if (!stop) timer = setTimeout(poll, 2000);
        }
      }
    }

    void poll();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [taskId, revision]);

  return { task, checkedAt, artifacts, queryError, artifactError, loading, refreshing, refresh: () => setRevision((value) => value + 1) };
}
