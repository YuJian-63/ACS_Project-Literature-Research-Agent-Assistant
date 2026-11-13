import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp } from 'antd';
import LocaleProvider from './i18n/LocaleProvider';
import { BrowserRouter } from 'react-router-dom';
import App, { AppErrorBoundary } from './App';
import 'antd/dist/reset.css';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><LocaleProvider><AntApp><AppErrorBoundary><BrowserRouter><App /></BrowserRouter></AppErrorBoundary></AntApp></LocaleProvider></StrictMode>,
);
