import { useCallback } from 'react';
import { agentResearch } from '../../api/agentResearch';
import { useLocale } from '../../i18n';
import { useResource } from '../../shared/hooks/useResource';

export function WorkflowLabel({ workflow }: { workflow?: string }) {
  const locale = useLocale();
  const label = workflow === 'baseline' ? 'Baseline' : workflow === 'extended' ? 'Extension'
    : locale === 'en-US' ? 'Workflow unavailable' : '流程类型不可用';
  return <span className={`record-workflow record-workflow-${workflow === 'baseline' || workflow === 'extended' ? workflow : 'unknown'}`}>{label}</span>;
}

export default function RecordWorkflow({ taskId }: { taskId: string }) {
  const locale = useLocale();
  const load = useCallback((signal: AbortSignal) => agentResearch.workflow(taskId, signal), [taskId]);
  const resource = useResource(load);
  if (resource.loading) return <span className="record-workflow" role="status">{locale === 'en-US' ? 'Loading workflow…' : '读取流程中…'}</span>;
  return <><WorkflowLabel workflow={resource.data?.workflow_type} />
    {resource.error && <button className="record-workflow-retry" type="button" onClick={resource.reload}>{locale === 'en-US' ? 'Retry' : '重试'}</button>}
  </>;
}
