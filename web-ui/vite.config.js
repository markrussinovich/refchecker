import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendTarget = process.env.VITE_BACKEND_URL || 'http://localhost:8000'
const devServerHost = process.env.VITE_HOST || '0.0.0.0'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: devServerHost,
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
    css: true,
    exclude: ['**/node_modules/**', '**/e2e/**'],
  },
})
