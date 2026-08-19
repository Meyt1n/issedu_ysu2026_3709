import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const publicDir = path.join(root, 'public')
const distDir = path.join(root, 'dist')
const swSource = fs.readFileSync(path.join(publicDir, 'sw.js'), 'utf8')
const mainSource = fs.readFileSync(path.join(root, 'src', 'main.ts'), 'utf8')
const manifest = JSON.parse(fs.readFileSync(path.join(publicDir, 'manifest.webmanifest'), 'utf8'))

function assert(condition, message) {
  if (!condition) throw new Error(`PWA 审计失败：${message}`)
}

function existsInDist(urlPath) {
  const relative = urlPath === '/' ? 'index.html' : urlPath.replace(/^\//, '')
  return fs.existsSync(path.join(distDir, relative))
}

assert(fs.existsSync(distDir), '请先运行 npm run build 生成 dist/')
assert(fs.existsSync(path.join(distDir, 'sw.js')), '构建产物缺少 sw.js')
assert(mainSource.includes("navigator.serviceWorker.register('/sw.js')"), '生产入口没有注册 /sw.js')
assert(mainSource.includes('import.meta.env.PROD'), 'Service Worker 注册没有限制在生产环境')

const shellMatch = swSource.match(/const SHELL = \[(.*?)\]/s)
assert(shellMatch, '未找到应用外壳预缓存清单')
const shell = [...shellMatch[1].matchAll(/'([^']+)'/g)].map(match => match[1])
assert(shell.length >= 4, '应用外壳预缓存清单过短')
for (const resource of shell) assert(existsInDist(resource), `构建产物缺少外壳资源 ${resource}`)

assert(manifest.start_url === '/', 'manifest start_url 必须指向应用外壳 /')
assert(manifest.display === 'standalone', 'manifest display 必须支持独立应用外壳')
assert(Array.isArray(manifest.icons) && manifest.icons.length > 0, 'manifest 缺少应用图标')
for (const icon of manifest.icons) assert(existsInDist(icon.src), `构建产物缺少 manifest 图标 ${icon.src}`)

assert(swSource.includes("if (request.method !== 'GET') return"), '非 GET 请求未明确绕过缓存')
assert(swSource.includes('if (url.origin !== self.location.origin) return'), '跨源请求未明确绕过缓存')
assert(swSource.includes("url.pathname.startsWith('/api') || url.pathname.startsWith('/health')"), '/api 或 /health 未明确绕过缓存')
assert(swSource.includes("if (request.mode === 'navigate')"), '页面导航未单独采用离线策略')
assert(swSource.includes(".catch(() => caches.match('/'))"), '离线导航缺少应用外壳回退')
assert(swSource.includes('caches.match(request)'), '静态资源未采用缓存优先读取')
assert(swSource.includes('cache.put(request, copy)'), '静态资源未在成功回源后写入缓存')
assert(swSource.includes("cache.put('/', copy)"), '在线导航未更新应用外壳缓存')

console.log(`PWA 审计通过：${shell.length} 个外壳资源、${manifest.icons.length} 个图标资源均存在。`)
console.log('缓存边界通过：非 GET、跨源请求、/api 和 /health 均不会进入 Service Worker 缓存。')
console.log('离线策略通过：导航 network-first 并回退到 /，静态资源 cache-first。')
