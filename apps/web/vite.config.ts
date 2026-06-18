import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiProxyTarget = process.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8011';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5123,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true
      }
    }
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts'
  }
});
