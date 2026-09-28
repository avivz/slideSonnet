/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// The Python server this dev server proxies to (`slidesonnet edit --no-browser`).
const backend = process.env.SLIDESONNET_BACKEND ?? 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [vue()],
  // Built assets are served by the Python package from /ui/…; index.html itself
  // is served at / and /d/{token} by the same server.
  base: '/ui/',
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: {
    outDir: fileURLToPath(new URL('../src/slidesonnet/server/static', import.meta.url)),
    emptyOutDir: true,
    rollupOptions: {
      input: { index: fileURLToPath(new URL('./index.html', import.meta.url)) },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // SSE must stream: http-proxy passes chunks through as they arrive.
      '/api': { target: backend, changeOrigin: false },
      '/ssmedia': { target: backend },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
    restoreMocks: true,
  },
})
