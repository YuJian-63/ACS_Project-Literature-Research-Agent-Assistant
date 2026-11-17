import { useEffect, useRef, useState } from 'react';
import { api, asApiError, isCanceled, type ApiError } from '../../../api/client';
import type { AgentResult, Artifact, Task, TaskEvent } from '../../../api/types';
import { isTerminal } from '../../../shared/lib/format';

export function useTask(taskId: string) {
  const [task, setTask] = useState<Task>();
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [agentResult, setAgentResult] = useState<AgentResult | null>();
  const [artifacts, setArtifacts] = useState<Artifact[]>();
  const [queryError, setQueryError] = useState<ApiError>();
  const [eventError, setEventError] = useState<ApiError>();
  const [artifactError, setArtifactError] = useState<ApiError>();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [revision, setRevision] = useState(0);
  const latestTask = useRef<Task | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0;
    setEvents([]);

    async function readEvents() {
      try {
        let hasMore = true;
        while (hasMore && !controller.signal.aborted) {
          const page = await api.events(taskId, cursor, controller.signal);
          if (controller.signal.aborted) return;
          cursor = page.next_after_seq;
          setEvents((previous) => [...new Map([...previous, ...page.items].map((event) => [event.seq, event])).values()].sort((first, second) => first.seq - second.seq));
          hasMore = page.has_more;
        }
        if (!controller.signal.aborted) setEventError(undefined);
      } catch (error) {
        if (!controller.signal.aborted && !isCanceled(error)) setEventError(asApiError(error));
      }
    }

    async function poll() {
      setRefreshing(true);
      const eventRequest = readEvents();
      let stop = false;
      try {
        const result = await api.task(taskId, controller.signal);
        if (controller.signal.aborted) return;
        latestTask.current = result;
        setTask(result);
        setQueryError(undefined);
        stop = isTerminal(result.status);
        if (result.result_format === 'agent-v1' && isTerminal(result.status)) {
          try {
            const response = await api.agentResult(taskId, controller.signal);
            if (controller.signal.aborted) return;
            setAgentResult(response);
            setArtifactError(undefined);
          } catch (error) {
            if (!controller.signal.aborted && !isCanceled(error)) setArtifactError(asApiError(error));
          }
        } else if (result.status === 'succeeded') {
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
        await eventRequest;
        if (!controller.signal.aborted && stop && latestTask.current?.id === taskId && cursor < latestTask.current.last_event_seq) await readEvents();
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

  return { task, events, artifacts, agentResult, queryError, eventError, artifactError, loading, refreshing, refresh: () => setRevision((value) => value + 1) };
}
