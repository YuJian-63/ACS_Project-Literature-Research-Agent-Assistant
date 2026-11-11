import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), '');
  const target = environment.API_PROXY_TARGET || 'http://127.0.0.1:8000';
  const proxy = Object.fromEntries(
    ['/api', '/health', '/ready'].map((path) => [path, { target, changeOrigin: true }]),
  );
  return {
    plugins: [react()],
    server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
    build: { target: 'es2022' },
  };
});
