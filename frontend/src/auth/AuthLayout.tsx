import type { ReactNode } from 'react';
import { BookOutlined, FileSearchOutlined, NodeIndexOutlined, SafetyOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import LanguageSwitch from '../components/LanguageSwitch';
import { t, useLocale } from '../i18n';
import './auth.css';

export default function AuthLayout({ children }: { children: ReactNode }) {
  useLocale();
  return <div className="auth-shell">
    <a className="auth-skip" href="#auth-content">{t('跳转到账号表单')}</a>
    <header className="auth-header">
      <Link to="/login" className="auth-brand"><span className="auth-brand-mark"><BookOutlined aria-hidden="true" /></span><span>Literature<small>{t('文献研究助手')}</small></span></Link>
      <LanguageSwitch />
    </header>
    <main className="auth-main" id="auth-content" tabIndex={-1}>
      <section className="auth-panel">{children}</section>
      <aside className="auth-note" aria-label={t('文献研究助手')}>
        <div className="auth-note-intro"><h2>{t('让研究回到原文')}</h2><p>{t('从一篇论文开始，建立有据可循的研究。')}</p></div>
        <div className="auth-manuscript" aria-hidden="true">
          <div className="auth-paper auth-paper-back" /><div className="auth-paper auth-paper-middle" />
          <div className="auth-paper auth-paper-front"><BookOutlined /><span className="auth-paper-heading" /><span /><span /><span /><div className="auth-paper-excerpt"><span /><span /></div><span /><span /></div>
          <div className="auth-manuscript-caption"><NodeIndexOutlined />{t('原文、页码与引用，始终相连')}</div>
        </div>
        <ul className="auth-features">
          <li><BookOutlined aria-hidden="true" /><div><h3>{t('整理你的文献')}</h3><p>{t('导入论文，构建个人论文库。')}</p></div></li>
          <li><FileSearchOutlined aria-hidden="true" /><div><h3>{t('围绕问题开展研究')}</h3><p>{t('生成摘要、论文问答与跨论文综述。')}</p></div></li>
          <li><NodeIndexOutlined aria-hidden="true" /><div><h3>{t('沿着引用核对发现')}</h3><p>{t('从研究结果回到原文与页码。')}</p></div></li>
        </ul>
      </aside>
    </main>
    <footer className="auth-footer"><span>{t('研究始于阅读，也应能回到原文。')}</span><span><SafetyOutlined aria-hidden="true" />{t('论文与研究结果仅对你可见')}</span></footer>
  </div>;
}
