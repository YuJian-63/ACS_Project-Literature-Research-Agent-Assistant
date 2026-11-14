import type { ReactNode } from 'react';
import { Button, Spin } from 'antd';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthProvider';
import LanguageSwitch from '../components/LanguageSwitch';
import { t, useLocale } from '../i18n';

export default function AuthGate({ children }: { children: ReactNode }) {
  useLocale();
  const auth = useAuth();
  const location = useLocation();
  if (auth.status !== 'ready') return <div className="auth-loading"><LanguageSwitch />{auth.status === 'loading'
    ? <div role="status"><Spin /><p>{t('正在确认登录状态')}</p></div>
    : <div role="alert"><p>{t(auth.logoutFailed ? '退出未完成，请重试。' : '无法确认登录状态，请重试。')}</p><Button onClick={auth.logoutFailed ? () => { void auth.logout().catch(() => undefined); } : auth.reload}>{t('重试')}</Button></div>}</div>;
  if (!auth.user) return <Navigate to={'/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash)} replace />;
  return children;
}
