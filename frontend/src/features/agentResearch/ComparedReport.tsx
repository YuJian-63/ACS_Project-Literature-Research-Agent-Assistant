import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { AgentEvidence, AgentResearchRecord, AgentSource } from '../../api/agentResearch';
import { paperReaderUrl } from '../../shared/lib/paperReader';
import { resolveResearchSource } from './lib/researchSource';
import ResultContent from './ResultContent';
import SourceImportDialog from './SourceImportDialog';

type Target = { source: AgentSource; page?: number; citationKey?: string };
export default function ComparedReport({ record, section, onRequested }: { record: AgentResearchRecord; section: string; onRequested: () => void }) {
  const navigate = useNavigate();
  const [target, setTarget] = useState<Target>();
  function open(paperId: string, value: Target) {
    setTarget(undefined);
    navigate(paperReaderUrl(paperId, { page: value.page, researchReturn: { researchId: record.task_id, citationKey: value.citationKey } }));
  }
  function read(value: Target) {
    const resolved = resolveResearchSource(value.source);
    if (resolved.kind === 'local') open(resolved.paperId, value);
    else setTarget(value);
  }
  return <>
    {record.result && <ResultContent result={record.result} metrics={record.metrics} section={section} onEvaluationRequested={onRequested}
      onReadSource={source => read({ source })} onReadEvidence={(source: AgentEvidence) => read({ source, page: source.page, citationKey: source.chunk_id })} />}
    {target && <SourceImportDialog source={target.source} page={target.page} onClose={() => setTarget(undefined)} onRead={id => open(id, target)} />}
  </>;
}
