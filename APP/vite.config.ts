import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const homecareApi = process.env.HOMECARE_API ?? 'http://127.0.0.1:18800'

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
      '@hct/voice': fileURLToPath(new URL('../shared/voice', import.meta.url)),
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
