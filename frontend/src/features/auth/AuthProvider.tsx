import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { asApiError, isCanceled } from '../../api/client';
import { authPost, readSession, type AuthSession, type User } from '../../api/auth';
import { invalidateSession, registerUnauthorized, sessionSnapshot, setCsrfToken } from '../../api/session';
import { createUuid } from '../../shared/lib/uuid';

interface AuthState { user: User | null; status: 'loading' | 'ready' | 'error'; generation: number; logoutFailed?: boolean }
interface AuthContextValue extends AuthState {
  login: (username: string, password: string, signal: AbortSignal) => Promise<void>;
  logout: () => Promise<void>;
  endSession: () => void;
  reload: () => void;
}
const AuthContext = createContext<AuthContextValue | null>(null);
const channelName = 'literature-auth';

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ user: null, status: 'loading', generation: 0 });
  const channel = useRef<BroadcastChannel | null>(null);
  const pending = useRef<AbortController | null>(null);
  const notify = useCallback(() => {
    const eventId = createUuid();
    channel.current?.postMessage(eventId);
    try { localStorage.setItem(channelName, eventId); } catch {}
  }, []);

  const endSession = useCallback(() => {
    pending.current?.abort();
    const generation = invalidateSession();
    setState({ user: null, status: 'ready', generation });
    notify();
  }, [notify]);

  const reload = useCallback(() => {
    pending.current?.abort();
    const generation = invalidateSession();
    const controller = new AbortController();
    pending.current = controller;
    setState({ user: null, status: 'loading', generation });
    void readSession(controller.signal).then((session) => {
      if (controller.signal.aborted) return;
      setCsrfToken(session.csrf_token);
      setState({ user: session.user, status: 'ready', generation });
    }).catch((error) => {
      if (controller.signal.aborted || isCanceled(error)) return;
      setState({ user: null, status: asApiError(error).status === 401 ? 'ready' : 'error', generation });
    });
  }, []);

  useEffect(() => {
    const unregister = registerUnauthorized(endSession);
    let lastEvent: string | null = null;
    const changed = (eventId: unknown) => {
      if (typeof eventId !== 'string' || eventId === lastEvent) return;
      lastEvent = eventId;
      reload();
    };
    try {
      channel.current = new BroadcastChannel(channelName);
      channel.current.onmessage = (event: MessageEvent) => changed(event.data);
    } catch {}
    const storage = (event: StorageEvent) => { if (event.key === channelName) changed(event.newValue); };
    const restored = (event: PageTransitionEvent) => { if (event.persisted) reload(); };
    window.addEventListener('storage', storage);
    window.addEventListener('pageshow', restored);
    reload();
    return () => {
      unregister();
      pending.current?.abort();
      channel.current?.close();
      channel.current = null;
      window.removeEventListener('storage', storage);
      window.removeEventListener('pageshow', restored);
    };
  }, [endSession, reload]);

  const login = useCallback(async (username: string, password: string, signal: AbortSignal) => {
    const session = await authPost<AuthSession>('login', { username, password }, signal);
    pending.current?.abort();
    const generation = invalidateSession();
    setCsrfToken(session.csrf_token);
    setState({ user: session.user, status: 'ready', generation });
    notify();
  }, [notify]);

  const logout = useCallback(async () => {
    pending.current?.abort();
    const token = sessionSnapshot().csrfToken;
    const generation = invalidateSession();
    if (token) setCsrfToken(token);
    setState({ user: null, status: 'loading', generation });
    try {
      await authPost('logout', {}, undefined, true);
      endSession();
    } catch (error) {
      if (!isCanceled(error)) setState({ user: null, status: 'error', generation, logoutFailed: true });
      throw error;
    }
  }, [endSession]);

  return <AuthContext.Provider value={{ ...state, login, logout, endSession, reload }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('AuthProvider is required');
  return value;
}
