import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const apiTarget = process.env.HCT_API_PROXY ?? 'http://127.0.0.1:8000'
const webPort = Number(process.env.HCT_WEB_PORT ?? 5173)

const proxyOptions = {
  target: apiTarget,
  timeout: 30_000,
  proxyTimeout: 30_000,
}

export default defineConfig({
  root: 'src/web',
  plugins: [vue()],
  resolve: {
    alias: {
      '@hct/voice': fileURLToPath(new URL('../../shared/voice', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: webPort,
    strictPort: true,
    allowedHosts: ['.cpolar.cn', '.cpolar.top'],
    proxy: {
      '/health': proxyOptions,
      '/api': proxyOptions,
    },
  },
})
