import LanguageSwitch from '../shared/components/LanguageSwitch';
import { t, useLocale } from '../i18n';
import { Component, lazy, Suspense, type ReactNode } from 'react';
import { Button, Result, Spin } from 'antd';
import { BookOutlined, HistoryOutlined, PlusOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons';
import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from '../features/auth/AuthProvider';
import AuthGate from '../features/auth/components/AuthGate';
import AccountMenu from '../features/auth/components/AccountMenu';
import AuthPage from '../features/auth/pages/AuthPage';

const PapersPage = lazy(() => import('../features/papers/pages/PapersPage'));
const SearchPapersPage = lazy(() => import('../features/search/pages/SearchPapersPage'));
const NewTaskPage = lazy(() => import('../features/research/pages/NewTaskPage'));
const TasksPage = lazy(() => import('../features/research/pages/TasksPage'));
const TaskDetailPage = lazy(() => import('../features/research/pages/TaskDetailPage'));

function AppFailure() {
  useLocale();
  return <><div className="failure-language"><LanguageSwitch /></div><Result status="error" title={t("页面未能正常显示")} subTitle={t("请刷新页面重试，已保存的论文和任务不会丢失。")} extra={<Button onClick={() => window.location.reload()}>{t("刷新页面")}</Button>} /></>;
}

export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <AppFailure /> : this.props.children; }
}

export default function App() {
  const { generation } = useAuth();
  return <Routes>
    {['/login', '/register', '/verify-email', '/forgot-password', '/reset-password'].map((path) => <Route key={path} path={path} element={<AuthPage key={path} />} />)}
    <Route path="*" element={<AuthGate><AppErrorBoundary key={generation}><Workspace /></AppErrorBoundary></AuthGate>} />
  </Routes>;
}

function Workspace() {
  useLocale();
  const { user } = useAuth();
  const { pathname } = useLocation();
  const currentPage = pathname === '/papers/search' ? t('搜索论文') : pathname === '/tasks/new' ? t('新建研究') : pathname === '/tasks' ? t('研究记录') : pathname.startsWith('/tasks/') ? t('研究结果') : t('论文库');
  return <div className="workspace">
    <a href="#main-content" className="skip-link">{t('跳到主要内容')}</a>
    <aside className="sidebar">
      <Link className="brand" to="/papers" aria-label={t('研序，返回论文库')}><span className="brand-mark"><BookOutlined /></span><div><strong>Literature</strong><span>{t('文献研究工作台')}</span></div></Link>
      <Link className="sidebar-create" to="/tasks/new"><PlusOutlined />{t('新建研究')}</Link>
      <nav className="primary-nav" aria-label={t('主导航')}><NavLink to="/papers" end><BookOutlined />{t('论文库')}</NavLink><NavLink to="/papers/search"><SearchOutlined />{t('搜索论文')}</NavLink><NavLink to="/tasks"><HistoryOutlined />{t('研究记录')}</NavLink></nav>
      <div className="sidebar-note"><BookOutlined /><strong>{t('让研究回到原文')}</strong><p>{t('整理文献、比较观点，沿着引用核对每一项研究发现。')}</p></div>
      <div className="sidebar-footer"><span className="workspace-avatar">{user?.username.slice(0, 1).toUpperCase()}</span><div>{user?.username}<small>{t('个人研究空间')}</small></div></div>
    </aside>
    <div className="workspace-body">
      <header className="topbar"><div className="breadcrumb"><Link to="/papers" className="mobile-brand"><BookOutlined /></Link><Link to={pathname.startsWith('/tasks') ? '/tasks' : '/papers'}>{pathname.startsWith('/tasks') ? t('研究记录') : t('研究空间')}</Link><RightOutlined /><span>{pathname === '/account/password' ? t('修改密码') : currentPage}</span></div><div className="topbar-actions"><LanguageSwitch /><AccountMenu /></div></header>
      <nav className="mobile-nav" aria-label={t('移动导航')}><NavLink to="/papers" end>{t('论文库')}</NavLink><NavLink to="/papers/search">{t('搜索论文')}</NavLink><NavLink to="/tasks" end>{t('研究记录')}</NavLink><NavLink to="/tasks/new">{t('新建研究')}</NavLink></nav>
      <main id="main-content" tabIndex={-1}><Suspense fallback={<div className="page-loading"><Spin description={t('正在加载页面')} size="large"><div className="loading-placeholder" /></Spin></div>}><Routes>
        <Route path="/" element={<Navigate to="/papers" replace />} />
        <Route path="/papers" element={<PapersPage />} />
        <Route path="/papers/search" element={<SearchPapersPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/tasks/new" element={<NewTaskPage />} />
        <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        <Route path="/account/password" element={<AuthPage />} />
        <Route path="*" element={<Result status="404" title={t('页面不存在')} subTitle={t('你可以回到论文库，或从任务列表重新打开研究任务。')} extra={<Link to="/papers"><Button type="primary">{t('返回论文库')}</Button></Link>} />} />
      </Routes></Suspense></main>
      <footer className="workspace-footer"><span>{t('研究始于阅读，也应能回到原文。')}</span><span>Literature Research Assistant</span></footer>
    </div>
  </div>;
}
