import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 联机模式下，开发服务器把 API 请求代理到家庭服务器（主仓库 FastAPI）。
// 默认 18800（避开常被占用的 8000/8001）；可用环境变量覆盖，
// 例如：HOMECARE_API=http://127.0.0.1:8001（连别人的实例）
const homecareApi = process.env.HOMECARE_API ?? 'http://127.0.0.1:18800'

// MOB-142：把版本号、构建时间与源码提交哈希注入产物，页面不再展示
// 无法证明来源的固定版本文案；构建机可用环境变量覆盖（CI 无 git 时必需）。
function gitCommit(): string {
  const override = process.env.APP_BUILD_COMMIT
  if (override) return override
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], { encoding: 'utf8' }).trim()
  } catch {
    return 'unknown'
  }
}

const pkg = JSON.parse(readFileSync(fileURLToPath(new URL('./package.json', import.meta.url)), 'utf-8')) as { version: string }
const buildInfo = {
  __APP_VERSION__: JSON.stringify(pkg.version),
  __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  __BUILD_COMMIT__: JSON.stringify(gitCommit()),
}

export default defineConfig({
  plugins: [vue()],
  define: buildInfo,
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
