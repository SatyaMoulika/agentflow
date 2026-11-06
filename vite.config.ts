import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
const proxyTarget = process.env.AGENTFLOW_API_PROXY_TARGET || 'http://127.0.0.1:8000';
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: proxyTarget, changeOrigin: false } },
  },
  preview: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: proxyTarget, changeOrigin: false } },
  },
  test: { environment: 'node', include: ['tests/**/*.test.{ts,tsx}'] },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'workflow-canvas': ['@xyflow/react'],
          charts: ['recharts'],
        },
      },
    },
  },
});
