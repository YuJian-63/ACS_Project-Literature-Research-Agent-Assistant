export function safeReturnPath(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020\u007f]/.test(value)) return '/papers';
  try {
    const decoded = decodeURIComponent(value);
    if (decoded.startsWith('//') || /[\\\u0000-\u0020\u007f]/.test(decoded)) return '/papers';
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin || /^\/(login|register|verify-email|forgot-password|reset-password)(\/|$)/.test(url.pathname)) return '/papers';
    return url.pathname + url.search + url.hash;
  } catch { return '/papers'; }
}

let emailLink: { pathname: string; token: string } | undefined;

export function captureEmailLink() {
  if (!['/verify-email', '/reset-password'].includes(window.location.pathname)) return;
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token') || '';
  emailLink = { pathname: window.location.pathname, token };
  window.history.replaceState(window.history.state, '', window.location.pathname);
}

export function readEmailToken(pathname: string) {
  return emailLink?.pathname === pathname ? emailLink.token : '';
}
export function forgetEmailToken() { emailLink = undefined; }
