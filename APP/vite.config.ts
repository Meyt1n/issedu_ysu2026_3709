import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 联机模式下，开发服务器把 API 请求代理到家庭服务器（主仓库 FastAPI）。
// 默认 18800（避开常被占用的 8000/8001）；可用环境变量覆盖，
// 例如：HOMECARE_API=http://127.0.0.1:8001（连别人的实例）
const homecareApi = process.env.HOMECARE_API ?? 'http://127.0.0.1:18800'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5175,
    proxy: {
      '/api': { target: homecareApi, changeOrigin: true },
      '/health': { target: homecareApi, changeOrigin: true },
    },
  },
})
