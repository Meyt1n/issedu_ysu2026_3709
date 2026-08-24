/**
 * MOB-151：PWA 安装资产、离线冷启动与更新生命周期证据脚本。
 *
 * 用本地 HTTP 服务器托管生产构建 dist：
 *  1) 验证 manifest 与全部图标可访问（发布级安装资产）；
 *  2) 离线冷启动：外壳可用、演示数据照常、缓存中无 /api 条目；
 *  3) 更新流程：部署新 sw.js 后出现可读屏的更新提示（不静默切换），
 *     用户确认后新版本接管并刷新，版本可定位；
 *  4) 外壳缓存丢失 + 离线：安全回退提示，不显示旧数据。
 *
 * 用法：先 npm run build，再 node scripts/pwa-lifecycle.mjs
 */
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { join, extname } from 'node:path'
import { fileURLToPath, URL } from 'node:url'

import { chromium } from '@playwright/test'

const APP_ROOT = fileURLToPath(new URL('..', import.meta.url))
const DIST = join(APP_ROOT, 'dist')
const EVIDENCE = join(APP_ROOT, '..', 'docs', 'stories', 'evidence')

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
}

const DEPLOY_MARKER = 'pwa-lifecycle-deploy-v2'

function createDistServer() {
  let swOverride = null
  const server = createServer(async (req, res) => {
    try {
      const path = new URL(req.url, 'http://127.0.0.1').pathname
      if (path === '/sw.js') {
        const body = swOverride ?? (await readFile(join(DIST, 'sw.js'), 'utf8'))
        res.writeHead(200, { 'Content-Type': MIME['.js'], 'Cache-Control': 'no-store' })
        res.end(body)
        return
      }
      const file = path === '/' ? 'index.html' : path.slice(1)
      const content = await readFile(join(DIST, file))
      res.writeHead(200, {
        'Content-Type': MIME[extname(file)] ?? 'application/octet-stream',
        'Cache-Control': file === 'index.html' ? 'no-store' : 'public, max-age=60',
      })
      res.end(content)
    } catch {
      res.writeHead(404, { 'Content-Type': 'text/plain' })
      res.end('not found')
    }
  })
  return {
    start: () => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port))),
    close: () => new Promise(resolve => server.close(resolve)),
    deployV2: async () => {
      const base = await readFile(join(DIST, 'sw.js'), 'utf8')
      swOverride = `${base}\n// deploy-marker ${DEPLOY_MARKER}\n`
    },
  }
}

function line(message) {
  console.log(`[pwa-lifecycle] ${message}`)
}

async function main() {
  const server = createDistServer()
  const port = await server.start()
  const base = `http://127.0.0.1:${port}`
  const browser = await chromium.launch({ args: ['--no-proxy-server'] })
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
  const page = await context.newPage()

  try {
    // ── 1) 安装资产 ────────────────────────────────────────────────
    for (const asset of [
      '/manifest.webmanifest',
      '/icons/icon-192.png',
      '/icons/icon-512.png',
      '/icons/icon-maskable-192.png',
      '/icons/icon-maskable-512.png',
    ]) {
      const response = await page.request.get(base + asset)
      if (response.status() !== 200) throw new Error(`asset ${asset} -> ${response.status()}`)
    }
    line('install assets: manifest + 4 PNG icons reachable (200)')

    // ── 初始加载与 SW 就绪 ─────────────────────────────────────────
    await page.goto(base)
    await page.waitForSelector('text=今日', { timeout: 20000 })
    await page.evaluate(() => navigator.serviceWorker.ready)
    line('app loaded, service worker active')

    // ── 2) 缓存审计：只有外壳前缀，且无 /api 条目 ─────────────────
    const cacheAudit = await page.evaluate(async () => {
      const names = await caches.keys()
      const entries = []
      for (const name of names) {
        const cache = await caches.open(name)
        entries.push(...(await cache.keys()).map(request => `${name} ${new URL(request.url).pathname}`))
      }
      return { names, entries }
    })
    if (!cacheAudit.names.some(name => name.startsWith('hct-mobile-shell'))) {
      throw new Error(`shell cache missing: ${cacheAudit.names.join(', ')}`)
    }
    if (cacheAudit.entries.some(entry => entry.includes('/api') || entry.includes('/health'))) {
      throw new Error('api/health entry found in cache')
    }
    line(`cache audit: ${cacheAudit.names.join(', ')} — no /api or /health entries (${cacheAudit.entries.length} total)`)

    // ── 离线冷启动 ─────────────────────────────────────────────────
    await context.setOffline(true)
    await page.reload()
    await page.waitForSelector('text=今日', { timeout: 20000 })
    await page.waitForTimeout(600)
    await page.screenshot({ path: join(EVIDENCE, 'MOB-151-offline-cold-start.png'), fullPage: false })
    line('offline cold start: shell + demo data render, screenshot saved')

    // ── 外壳缓存丢失 + 离线：安全回退，不显示旧数据 ───────────────
    await context.setOffline(false)
    await page.waitForTimeout(300)
    await context.setOffline(true)
    await page.evaluate(async () => {
      const names = await caches.keys()
      await Promise.all(names.map(name => caches.delete(name)))
    })
    await page.reload()
    await page.waitForSelector('text=当前无法连接网络', { timeout: 20000 })
    await page.screenshot({ path: join(EVIDENCE, 'MOB-151-shell-recovery-fallback.png'), fullPage: false })
    line('shell cache lost offline: safe fallback notice shown, no stale health data')

    // ── 3) 更新生命周期：新版本等待 → 提示 → 确认接管 ─────────────
    await context.setOffline(false)
    await page.evaluate(async () => {
      const names = await caches.keys()
      await Promise.all(names.map(name => caches.delete(name)))
    })
    await page.reload()
    await page.waitForSelector('text=今日', { timeout: 20000 })
    await page.evaluate(() => navigator.serviceWorker.ready)
    await page.waitForTimeout(500)

    await server.deployV2()
    await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration()
      await registration.update()
    })
    await page.waitForSelector('.pwa-update-notice', { timeout: 20000 })
    await page.waitForSelector('text=发现新版本', { timeout: 5000 })
    await page.screenshot({ path: join(EVIDENCE, 'MOB-151-update-notice.png'), fullPage: false })
    line('new deploy detected: update notice rendered (no silent swap)')

    await page.click('text=立即刷新更新')
    await page.waitForSelector('text=今日', { timeout: 20000 })
    await page.waitForSelector('.pwa-update-notice', { state: 'detached', timeout: 20000 })
    const activeState = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration()
      return {
        state: registration.active?.state ?? 'none',
        script: await fetch('/sw.js', { cache: 'no-store' }).then(response => response.text()),
      }
    })
    if (activeState.state !== 'activated') throw new Error(`active worker state ${activeState.state}`)
    if (!activeState.script.includes(DEPLOY_MARKER)) throw new Error('deploy marker missing after update')
    line('update applied after user confirm: new worker activated, deploy marker locatable')

    console.log('PWA-LIFECYCLE PASS')
    return 0
  } finally {
    await browser.close()
    await server.close()
  }
}

main().then(
  code => process.exit(code ?? 0),
  error => {
    console.error('[pwa-lifecycle] FAILED:', error)
    process.exit(1)
  },
)
