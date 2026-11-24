import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp } from 'antd';
import LocaleProvider from './i18n/LocaleProvider';
import { BrowserRouter } from 'react-router-dom';
import App, { AppErrorBoundary } from './app/App';
import AuthProvider from './features/auth/AuthProvider';
import { captureEmailLink } from './features/auth/lib/links';
import 'antd/dist/reset.css';
import './app/styles.css';

captureEmailLink();

createRoot(document.getElementById('root')!).render(
  <StrictMode><LocaleProvider><AntApp message={{ duration: 3, maxCount: 3 }} notification={{ duration: 3 }}><BrowserRouter><AuthProvider><AppErrorBoundary><App /></AppErrorBoundary></AuthProvider></BrowserRouter></AntApp></LocaleProvider></StrictMode>,
);
