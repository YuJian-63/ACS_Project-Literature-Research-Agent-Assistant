import { request } from './client';

export type ModelState = 'requested' | 'submitting' | 'unreachable' | 'unconfirmed' | 'queued' | 'loading' | 'ready' | 'stopping' | 'stopped' | 'failed';
export interface Models {
  bailian_config: 'local' | 'remote' | 'missing';
  generation: string | null;
  bailian_name: string | null;
  enabled: boolean;
  state: ModelState;
  owner: boolean;
  job_id: string | null;
  base_url: string | null;
  shared_url: string | null;
  detail: string | null;
  requested_at: string | null;
  checked_at: string | null;
}
export const loadModels = (signal: AbortSignal) => request<Models>({ url: '/api/v1/models', signal });
export const pollModels = () => true;
export const changeService = (action: 'start' | 'stop', generation?: string | null) =>
  request({ method: 'POST', url: '/api/v1/models/tacc/' + action, params: generation ? {generation} : undefined });

export const setModelUrl = (url: string) => url
  ? request({method: 'PUT', url: '/api/v1/models/shared', data: {base_url: url}})
  : request({method: 'DELETE', url: '/api/v1/models/shared'});

export const courseAvailable = (models?: Models) => Boolean(models?.enabled && models.state === 'ready');
