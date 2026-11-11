import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { BrowserRouter } from 'react-router-dom';
import App, { AppErrorBoundary } from './App';
import 'antd/dist/reset.css';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><ConfigProvider locale={zhCN} theme={{ token: {
    colorPrimary: '#315bd6', colorInfo: '#315bd6', borderRadius: 8, colorText: '#22314b',
    colorTextSecondary: '#64748b', colorBorder: '#dce3ed', fontSize: 14,
    fontFamily: '"Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  } }}><AntApp><AppErrorBoundary><BrowserRouter><App /></BrowserRouter></AppErrorBoundary></AntApp></ConfigProvider></StrictMode>,
);
