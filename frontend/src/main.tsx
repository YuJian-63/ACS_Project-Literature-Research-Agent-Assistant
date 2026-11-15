import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp } from 'antd';
import LocaleProvider from './i18n/LocaleProvider';
import { BrowserRouter } from 'react-router-dom';
import App, { AppErrorBoundary } from './App';
import AuthProvider from './auth/AuthProvider';
import { captureEmailLink } from './auth/links';
import 'antd/dist/reset.css';
import './styles.css';

captureEmailLink();

createRoot(document.getElementById('root')!).render(
  <StrictMode><LocaleProvider><AntApp><BrowserRouter><AuthProvider><AppErrorBoundary><App /></AppErrorBoundary></AuthProvider></BrowserRouter></AntApp></LocaleProvider></StrictMode>,
);
