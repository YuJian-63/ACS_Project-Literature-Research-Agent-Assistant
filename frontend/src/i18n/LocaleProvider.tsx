import { useEffect, type ReactNode } from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import { t, useLocale } from './index';

const theme = { token: {
  colorPrimary: '#176352', colorInfo: '#176352', borderRadius: 5, colorText: '#213a38',
  colorTextSecondary: '#536e69', colorBorder: '#dbe5e1', colorBgLayout: '#f0f5f4', fontSize: 14,
  colorSuccess: '#246647', colorWarning: '#8a601a', colorError: '#a33b36',
  fontFamily: '"Research Sans", "Noto Sans SC", "Microsoft YaHei", sans-serif',
} };

export default function LocaleProvider({ children }: { children: ReactNode }) {
  const locale = useLocale();
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = t('研序 · Literature Research Assistant');
    document.querySelector('meta[name="description"]')?.setAttribute('content', t('文献研究工作台'));
  }, [locale]);
  return <ConfigProvider locale={locale === 'en-US' ? enUS : zhCN} theme={theme}>{children}</ConfigProvider>;
}
