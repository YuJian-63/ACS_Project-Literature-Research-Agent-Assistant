import type { ReactNode } from 'react';
import { Button, Spin } from 'antd';
import { SafetyOutlined, ReloadOutlined } from '@ant-design/icons';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../AuthProvider';
import AuthLayout from './AuthLayout';
import { t, useLocale } from '../../../i18n';

export default function AuthGate({ children }: { children: ReactNode }) {
  useLocale();
  const auth = useAuth();
  const location = useLocation();
  if (auth.status !== 'ready') return <AuthLayout><div className="auth-gate-state">{auth.status === 'loading'
    ? <div role="status" aria-live="polite"><div className="auth-state-mark"><Spin size="large" /></div><h1>{t('正在确认登录状态')}</h1><p>{t('正在连接你的个人研究空间，请稍候。')}</p></div>
    : <div role="alert"><div className="auth-state-mark"><SafetyOutlined aria-hidden="true" /></div><h1>{t('暂时无法进入研究空间')}</h1><p>{t(auth.logoutFailed ? '退出未完成，请重试。' : '无法确认登录状态，请重试。')}</p><Button aria-label={t('重试')} type="primary" icon={<ReloadOutlined />} onClick={auth.logoutFailed ? () => { void auth.logout().catch(() => undefined); } : auth.reload}>{t('重试')}</Button></div>}</div></AuthLayout>;
  if (!auth.user) return <Navigate to={'/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash)} replace />;
  return children;
}
