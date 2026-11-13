import { useEffect, type ReactNode } from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import { t, useLocale } from './index';

const theme = { token: {
  colorPrimary: '#315bd6', colorInfo: '#315bd6', borderRadius: 8, colorText: '#22314b',
  colorTextSecondary: '#64748b', colorBorder: '#dce3ed', fontSize: 14,
  fontFamily: '"Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
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
