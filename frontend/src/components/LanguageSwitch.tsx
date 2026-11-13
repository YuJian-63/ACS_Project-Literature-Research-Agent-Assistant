import { GlobalOutlined } from '@ant-design/icons';
import { setLocale, useLocale, type Locale } from '../i18n';

export default function LanguageSwitch() {
  const locale = useLocale();
  return <label className="language-switch"><GlobalOutlined aria-hidden="true" /><select aria-label="界面语言 / Interface language" value={locale} onChange={(event) => setLocale(event.target.value as Locale)}><option value="zh-CN">中文</option><option value="en-US">English</option></select></label>;
}
