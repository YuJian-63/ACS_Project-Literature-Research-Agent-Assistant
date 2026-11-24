import { defaultResearch, type AgentResearchRecord, type ResearchWorkflowType } from '../../../api/agentResearch';
import type { ResearchDraft } from '../../../shared/lib/researchDraft';
import { reportedConfig } from './reportComparison';

export function retryResearchDraft(record: AgentResearchRecord, workflow?: ResearchWorkflowType): { draft: ResearchDraft; missing: string[] } {
  const config = reportedConfig(record);
  const missing: string[] = [];
  const research = { ...defaultResearch };
  if (workflow) research.workflow = workflow === 'extended' ? 'extension' : 'baseline';
  else if (config.workflow === 'extension') research.workflow = 'extension';
  else if (config.workflow === 'baseline') research.workflow = 'baseline';
  else missing.push('workflow');
  if (config.model_provider === 'tacc' || config.model_provider === 'bailian' || config.model_provider === 'custom') research.model_provider = config.model_provider;
  else missing.push('model_provider');
  if (config.context_policy === 'compact' || config.context_policy === 'CompactHistory') research.context_policy = 'compact';
  else if (config.context_policy === 'full' || config.context_policy === 'FullHistory') research.context_policy = 'full';
  else missing.push('context_policy');
  if (research.workflow === 'extension') {
    for (const flag of ['planner', 'reflection'] as const) {
      if (typeof config[flag] === 'boolean') research[flag] = config[flag];
      else missing.push(flag);
    }
  }
  if (research.model_provider === 'custom') {
    if (typeof config.endpoint_url === 'string') research.endpoint_url = config.endpoint_url;
    else missing.push('endpoint_url');
  }
  const allowSearch = typeof config.allow_search === 'boolean' ? config.allow_search : true;
  if (typeof config.allow_search !== 'boolean') missing.push('allow_search');
  return { draft: { question: record.question, paperIds: [...record.paper_ids], research, allowSearch }, missing };
}
