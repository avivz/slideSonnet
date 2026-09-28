/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// The Python server this dev server proxies to (`slidesonnet edit --no-browser`).
const backend = process.env.SLIDESONNET_BACKEND ?? 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [vue()],
  // Built assets are served by the Python package from /ui/…; index.html itself
  // is served at / (and, later, at the deck routes) by the same server.
  base: '/ui/',
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: {
    outDir: fileURLToPath(new URL('../src/slidesonnet/server/static', import.meta.url)),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: fileURLToPath(new URL('./index.html', import.meta.url)),
        // Loaded by the NiceGUI editor page at a stable URL (/ui/embed/playback.js).
        playback: fileURLToPath(new URL('./src/features/playback/embed.ts', import.meta.url)),
      },
      output: {
        entryFileNames: (chunk) =>
          chunk.name === 'playback' ? 'embed/playback.js' : 'assets/[name]-[hash].js',
      },
      // The embed has no importer; keep its side effect (window.ssPlayback).
      preserveEntrySignatures: 'allow-extension',
    },
  },
  server: {
    port: 5173,
    proxy: {
      // SSE must stream: http-proxy passes chunks through as they arrive.
      '/api': { target: backend, changeOrigin: false },
      '/ssmedia': { target: backend },
      '/d/': { target: backend },
      '/_nicegui': { target: backend, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
    restoreMocks: true,
  },
})
