import { useEffect, useRef, useState } from 'react';
import { evaluations, type EvaluationVersion } from '../../api/evaluations';
import { asApiError, isCanceled, type ApiError } from '../../api/client';
import type { EvaluationMetrics } from '../../api/taskMetrics';

export function useEvaluation(taskId: string | undefined, evaluation: EvaluationMetrics | undefined, onRequested?: () => void) {
  const [state, setState] = useState<{ key: string; version?: EvaluationVersion; error?: ApiError; loading?: boolean }>({ key: '' });
  const [submission, setSubmission] = useState<{ taskId?: string; busy: boolean; error?: ApiError }>({ busy: false });
  const [revision, setRevision] = useState(0);
  const post = useRef<AbortController | null>(null);
  const key = `${taskId || ''}:${evaluation?.evaluation_id || ''}:${evaluation?.status || ''}`;
  useEffect(() => {
    const controller = new AbortController();
    setState({ key });
    if (taskId && evaluation?.evaluation_id) {
      setState({ key, loading: true });
      void evaluations.get(taskId, evaluation.evaluation_id, controller.signal).then(version => {
        if (!controller.signal.aborted) setState({ key, version });
      }).catch(error => {
        if (!controller.signal.aborted && !isCanceled(error)) setState({ key, error: asApiError(error) });
      });
    }
    return () => controller.abort();
  }, [taskId, evaluation?.evaluation_id, evaluation?.status, key, revision]);
  useEffect(() => {
    setSubmission({ busy: false });
    return () => { post.current?.abort(); post.current = null; };
  }, [taskId]);
  async function request(refreshEvidence = false) {
    if (!taskId || post.current) return;
    const controller = new AbortController();
    post.current = controller;
    setSubmission({ taskId, busy: true });
    try {
      await evaluations.request(taskId, controller.signal, refreshEvidence);
      if (!controller.signal.aborted) { setRevision(n => n + 1); onRequested?.(); }
    } catch (error) {
      if (!controller.signal.aborted && !isCanceled(error)) setSubmission({ taskId, busy: false, error: asApiError(error) });
    } finally {
      if (!controller.signal.aborted) setSubmission(previous => ({ ...previous, busy: false }));
      if (post.current === controller) post.current = null;
    }
  }
  const current = state.key === key ? state : undefined;
  return { version: current?.version, error: current?.error, loading: current?.loading,
    busy: submission.taskId === taskId && submission.busy,
    submitError: submission.taskId === taskId ? submission.error : undefined,
    request, reload: () => setRevision(n => n + 1) };
}
