import { useState } from 'react';
import { Alert, Button, Dropdown } from 'antd';
import { UserOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuth } from './AuthProvider';
import { isCanceled } from '../api/client';
import { t, useLocale } from '../i18n';

export default function AccountMenu() {
  useLocale();
  const auth = useAuth();
  const navigate = useNavigate();
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  return <div className="account-menu">{failed ? <Alert type="error" title={t('退出未完成，请重试。')} closable onClose={() => setFailed(false)} /> : null}<Dropdown trigger={['click']} menu={{
    items: [{ key: 'password', label: t('修改密码') }, { key: 'logout', label: t('退出登录'), danger: true }],
    onClick: ({ key }) => {
      if (key === 'password') navigate('/account/password');
      else if (!busy) {
        setBusy(true);
        void auth.logout().catch((error) => { if (!isCanceled(error)) setFailed(true); }).finally(() => setBusy(false));
      }
    },
  }}><Button aria-label={auth.user?.username} icon={<UserOutlined aria-hidden />} loading={busy} className="account-trigger">{auth.user?.username}</Button></Dropdown></div>;
}
