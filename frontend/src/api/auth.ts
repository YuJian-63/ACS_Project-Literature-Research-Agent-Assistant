import { request } from './client';
import { getLocale } from '../i18n/store';

export interface User { id: string; username: string; email: string }
export interface AuthSession { user: User; csrf_token: string }

export function authPost<T = void>(action: string, data: Record<string, string>, signal?: AbortSignal, authenticated = false) {
  return request<T>({ url: '/api/v1/auth/' + action, method: 'POST', data, signal, headers: { 'Content-Type': 'application/json', 'Accept-Language': getLocale() } }, !authenticated);
}

export function readSession(signal: AbortSignal) {
  return request<AuthSession>({ url: '/api/v1/auth/me', signal }, true);
}
