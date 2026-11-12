import { Component, lazy, Suspense, type ReactNode } from 'react';
import { Button, Result, Spin } from 'antd';
import { ArrowRightOutlined, BookOutlined, ExperimentOutlined, ProfileOutlined, SearchOutlined } from '@ant-design/icons';
import { Link, Navigate, NavLink, Route, Routes } from 'react-router-dom';

const PapersPage = lazy(() => import('./pages/PapersPage'));
const SearchPapersPage = lazy(() => import('./pages/SearchPapersPage'));
const NewTaskPage = lazy(() => import('./pages/NewTaskPage'));
const TasksPage = lazy(() => import('./pages/TasksPage'));
const TaskDetailPage = lazy(() => import('./pages/TaskDetailPage'));

export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <Result status="error" title="页面未能正常显示" subTitle="请刷新页面重试，已保存的论文和任务不会丢失。" extra={<Button onClick={() => window.location.reload()}>刷新页面</Button>} /> : this.props.children;
  }
}

export default function App() {
  return <div className="workspace">
    <a href="#main-content" className="skip-link">跳到主要内容</a>
    <aside className="sidebar">
      <Link className="brand" to="/papers" aria-label="研序，返回论文库"><span className="brand-mark"><BookOutlined /></span><div><strong>研序</strong><span>文献研究工作台</span></div></Link>
      <div className="workspace-label">研究空间</div>
      <nav className="primary-nav" aria-label="主导航"><NavLink to="/papers" end><BookOutlined />论文库</NavLink><NavLink to="/papers/search"><SearchOutlined />搜索论文</NavLink><NavLink to="/tasks"><ProfileOutlined />研究任务</NavLink></nav>
      <div className="sidebar-note"><ExperimentOutlined /><strong>从资料到研究问题</strong><p>保存论文，提出问题，<br />在同一处查看执行与结果。</p><Link to="/tasks/new">创建研究任务 <ArrowRightOutlined /></Link></div>
      <div className="sidebar-footer">本地单用户工作区<span>资料与任务由后端持久化保存</span></div>
    </aside>
    <div className="workspace-body">
      <header className="topbar"><Link to="/papers" className="mobile-brand"><BookOutlined /> 研序</Link><span className="topbar-title">文献研究助手</span><span className="environment-label">本地工作区 <span className="mode-label">MVP-3</span></span></header>
      <nav className="mobile-nav" aria-label="移动导航"><NavLink to="/papers" end>论文库</NavLink><NavLink to="/papers/search">搜索论文</NavLink><NavLink to="/tasks" end>研究任务</NavLink><NavLink to="/tasks/new">新建任务</NavLink></nav>
      <div className="mock-notice"><ExperimentOutlined /><strong>执行模式由服务器配置</strong><span>支持 PDF 解析与带来源的研究任务；模拟任务会在详情中标明，不作为真实研究结论。</span></div>
      <main id="main-content" tabIndex={-1}><Suspense fallback={<div className="page-loading"><Spin description="正在加载页面" size="large"><div className="loading-placeholder" /></Spin></div>}><Routes>
        <Route path="/" element={<Navigate to="/papers" replace />} />
        <Route path="/papers" element={<PapersPage />} />
        <Route path="/papers/search" element={<SearchPapersPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/tasks/new" element={<NewTaskPage />} />
        <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        <Route path="*" element={<Result status="404" title="页面不存在" subTitle="你可以回到论文库，或从任务列表重新打开研究任务。" extra={<Link to="/papers"><Button type="primary">返回论文库</Button></Link>} />} />
      </Routes></Suspense></main>
      <footer className="workspace-footer">研序 · Literature Research Assistant<span>研究结论需要真实来源与证据支持</span></footer>
    </div>
  </div>;
}
