import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const apiTarget = process.env.HCT_API_PROXY ?? 'http://127.0.0.1:8000'
const webPort = Number(process.env.HCT_WEB_PORT ?? 5173)

// 代理空闲超时必须 ≥ 客户端最慢的有界超时（助手非流式 240s、人脸注册/登录
// 首次可含模型下载 120s），否则 dev 代理会先掐断仍在处理的请求，前端只能
// 看到连接错误并误报「本地 API 不可用」（HCT-424）。
const proxyOptions = {
  target: apiTarget,
  timeout: 240_000,
  proxyTimeout: 240_000,
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
