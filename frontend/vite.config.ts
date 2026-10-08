import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: { host: '0.0.0.0', proxy: { '/api': { target: process.env.API_PROXY_TARGET || 'http://localhost:8080', changeOrigin: true } } },
  preview: { host: '0.0.0.0', proxy: { '/api': { target: process.env.API_PROXY_TARGET || 'http://localhost:8080', changeOrigin: true } } },
})
