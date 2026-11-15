let generation = 0;
let controller = new AbortController();
let csrfToken: string | null = null;
let onUnauthorized: (() => void) | undefined;

export function sessionSnapshot() {
  return { generation, signal: controller.signal, csrfToken };
}

export function invalidateSession() {
  controller.abort();
  controller = new AbortController();
  csrfToken = null;
  return ++generation;
}

export function setCsrfToken(token: string) { csrfToken = token; }
export function registerUnauthorized(handler: () => void) {
  onUnauthorized = handler;
  return () => { if (onUnauthorized === handler) onUnauthorized = undefined; };
}
export function unauthorized() { onUnauthorized?.(); }
