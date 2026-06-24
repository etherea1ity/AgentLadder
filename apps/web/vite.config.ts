import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiProxyTarget = process.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8011';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          const normalized = id.replace(/\\/g, '/');
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(normalized)) {
            return 'vendor-react';
          }
          if (normalized.includes('/node_modules/@rive-app/')) {
            return 'vendor-rive';
          }
          if (
            normalized.includes('/node_modules/lucide-react/') ||
            normalized.includes('/node_modules/lucide/')
          ) {
            return 'vendor-icons';
          }
          if (
            normalized.includes('/node_modules/katex/') ||
            /[\\/]node_modules[\\/](react-markdown|remark-|rehype-|micromark|mdast|hast|unist|vfile|unified|trough|bail|devlop|zwitch|ccount|markdown-table|trim-lines|parse-entities|stringify-entities|character-entities|comma-separated-tokens|space-separated-tokens|property-information|decode-named-character-reference|escape-string-regexp|html-url-attributes|is-plain-obj)[\\/]/.test(normalized)
          ) {
            return 'vendor-markdown';
          }
          return undefined;
        }
      }
    }
  },
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
