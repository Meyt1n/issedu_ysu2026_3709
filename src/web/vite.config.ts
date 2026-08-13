import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 本地多人联调时可用 HCT_API_PROXY 指向自己的后端实例，HCT_WEB_PORT 指定前端端口；
// 默认仍为 8000 / 5173，不影响既有脚本。
const apiTarget = process.env.HCT_API_PROXY ?? 'http://127.0.0.1:8000'
const webPort = Number(process.env.HCT_WEB_PORT ?? 5173)

// 代理层设置超时：偶发的响应丢失会在有限时间内断开，
// 让浏览器侧 fetch 收到错误并走客户端超时/重试兜底，而不是永久挂起。
const proxyOptions = {
  target: apiTarget,
  timeout: 30_000,
  proxyTimeout: 30_000,
}

export default defineConfig({
  root: 'src/web',
  plugins: [vue()],
  server: {
    port: webPort,
    strictPort: true,
    proxy: {
      '/health': proxyOptions,
      '/api': proxyOptions,
    },
  },
})
