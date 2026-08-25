import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const apiTarget = process.env.HCT_API_PROXY ?? 'http://127.0.0.1:8000'

// 代理空闲超时必须 ≥ 客户端最慢的有界超时（助手非流式 240s、人脸注册/登录
// 首次可含模型下载 120s），否则 dev 代理会先掐断仍在处理的请求，前端只能
// 看到连接错误并误报「本地 API 不可用」（HCT-424）。
const proxyOptions = {
  target: apiTarget,
  timeout: 240_000,
  proxyTimeout: 240_000,
}

export default defineConfig(({ mode }) => {
  // HCT-453 分端口入口：`npm run dev:web:member|admin` 通过 --mode 传入门户，
  // 也可显式设置 VITE_PORTAL_MODE（如 HCT_WEB_PORT=5174 VITE_PORTAL_MODE=admin
  // npm run dev:web）。缺省保持 auto（裸开发入口，按账号角色进门户）。
  const portalMode =
    process.env.VITE_PORTAL_MODE ?? (mode === 'admin' || mode === 'member' ? mode : '')
  if (portalMode) {
    // 回写进程环境变量：Vite 会把 VITE_ 前缀的进程变量暴露到
    // import.meta.env（dev 与 build 一致），比 define 更可靠地覆盖开发服务器。
    process.env.VITE_PORTAL_MODE = portalMode
  }
  const defaultPort =
    portalMode === 'admin' ? Number(process.env.HCT_ADMIN_WEB_PORT ?? 5174) : 5173
  const webPort = Number(process.env.HCT_WEB_PORT ?? defaultPort)

  return {
    root: 'src/web',
    plugins: [vue()],
    resolve: {
      alias: {
        '@hct/voice': fileURLToPath(new URL('../../shared/voice', import.meta.url)),
      },
    },
    ...(portalMode
      ? { define: { 'import.meta.env.VITE_PORTAL_MODE': JSON.stringify(portalMode) } }
      : {}),
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
  }
})
