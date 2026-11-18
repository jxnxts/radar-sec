import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The radar server (uv run radar serve). Override with RADAR_API=http://host:port.
const api = process.env.RADAR_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: api, changeOrigin: true },
      '/ws': { target: api.replace(/^http/, 'ws'), ws: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 700 },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
    css: false,
  },
})
