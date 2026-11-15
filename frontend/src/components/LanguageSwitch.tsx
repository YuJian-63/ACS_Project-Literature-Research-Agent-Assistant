import { GlobalOutlined } from '@ant-design/icons';
import { setLocale, useLocale, type Locale } from '../i18n';

export default function LanguageSwitch() {
  const locale = useLocale();
  const languages: { value: Locale; label: string; name: string }[] = [
    { value: 'zh-CN', label: '中文', name: '中文' },
    { value: 'en-US', label: 'EN', name: 'English' },
  ];

  return <div className="language-switch" role="group" aria-label="界面语言 / Interface language">
    <span className="language-switch-icon" aria-hidden="true"><GlobalOutlined /></span>
    {languages.map((language) => <button
      key={language.value}
      type="button"
      className="language-switch-option"
      lang={language.value}
      aria-label={language.name}
      aria-pressed={locale === language.value}
      onClick={() => setLocale(language.value)}
    >{language.label}</button>)}
  </div>;
}
