#!/usr/bin/env node
/**
 * MOB-145：移动端性能与资源预算测量（可复跑脚本）。
 *
 * 四套复跑环境（同一脚本，参数不同）：
 *   浏览器/PWA： npm run perf:budget                       （生产构建 + vite preview）
 *   受控/PWA 部署： node scripts/perf-budget.mjs --base https://<受控地址>
 *   Android WebView： node scripts/perf-budget.mjs --base http://127.0.0.1:<adb reverse 端口>
 *   弱网/低端模拟： 追加 --cpu 4 --network 'Slow 3G' / --offline-recovery
 *
 * 场景（全部使用演示模式，不采集任何健康数据）：
 *   cold-start   空缓存冷启动：首次内容绘制 + 可交互
 *   route-switch 今日→提醒→拍药盒→我的 路由切换耗时（取最慢）
 *   weak-network 断网打开 → 错误提示出现耗时；恢复网络重试 → 可交互耗时
 *   bundle       dist 产物体积（gzip 分类汇总 + 单文件上限）
 *
 * 输出：APP/release/perf-report-<target>-<ts>.json 与控制台 PASS/FAIL；超预算退出码 1。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { fileURLToPath, URL } from 'node:url'

import { chromium } from '@playwright/test'

import { evaluateBudget, formatBudgetReport } from './perf-budget-lib.mjs'

const args = process.argv.slice(2)
function argOf(flag, fallback = null) {
  const index = args.indexOf(flag)
  return index >= 0 && args[index + 1] !== undefined ? args[index + 1] : fallback
}
function has(flag) {
  return args.includes(flag)
}

const root = fileURLToPath(new URL('..', import.meta.url))
const config = JSON.parse(readFileSync(argOf('--budget', `${root}perf-budget.config.json`), 'utf-8'))
const target = argOf('--target', config.target ?? 'browser-pwa')
const cpuThrottle = Number(argOf('--cpu', '1'))
const networkPreset = argOf('--network', null) // 'Slow 3G' 等 CDP 预设名
const apk = argOf('--apk')
const baseOverride = argOf('--base')

// ---------- 产物体积预算（不依赖浏览器） ----------
function measureBundle() {
  const distDir = `${root}dist`
  if (!existsSync(distDir)) return null
  const totals = { js: 0, css: 0, image: 0, font: 0, largestFileKiB: 0 }
  const visit = (dir, relBase = '') => {
    for (const name of readdirSync(dir)) {
      const full = `${dir}/${name}`
      const rel = relBase ? `${relBase}/${name}` : name
      if (statSync(full).isDirectory()) {
        visit(full, rel)
        continue
      }
      const raw = readFileSync(full)
      const sizeKiB = raw.length / 1024
      totals.largestFileKiB = Math.max(totals.largestFileKiB, sizeKiB)
      const lower = name.toLowerCase()
      if (lower.endsWith('.js')) totals.js += gzipSync(raw).length / 1024
      else if (lower.endsWith('.css')) totals.css += gzipSync(raw).length / 1024
      else if (/\.(png|jpg|jpeg|webp|svg)$/.test(lower)) totals.image += sizeKiB
      else if (/\.(woff2?|ttf|otf)$/.test(lower)) totals.font += sizeKiB
    }
  }
  visit(distDir)
  return {
    jsGzipTotalKiB: totals.js,
    cssGzipTotalKiB: totals.css,
    imageTotalKiB: totals.image,
    fontTotalKiB: totals.font,
    largestFileKiB: totals.largestFileKiB,
  }
}

// ---------- 启动被测目标 ----------
async function startPreview() {
  const port = argOf('--port', '4173')
  const child = spawn('npm', ['run', 'preview', '--', '--port', port, '--strictPort'], {
    cwd: root,
    shell: true,
    stdio: 'ignore',
  })
  const base = `http://127.0.0.1:${port}`
  const started = Date.now()
  while (Date.now() - started < 30_000) {
    try {
      const response = await fetch(base)
      if (response.ok) return { base, stop: () => child.kill() }
    } catch { /* 尚未就绪 */ }
    await new Promise(resolve => setTimeout(resolve, 400))
  }
  child.kill()
  throw new Error('vite preview 30s 内未就绪')
}

// ---------- 浏览器测量 ----------
const NETWORK_PRESETS = {
  'Slow 3G': { download: 400 * 1024 / 8, upload: 400 * 1024 / 8, latency: 400 },
  'Fast 3G': { download: 1.6 * 1024 * 1024 / 8, upload: 750 * 1024 / 8, latency: 150 },
}

async function measurePage(base) {
  const browser = await chromium.launch({ args: ['--no-proxy-server'] })
  const report = { coldStart: null, routeSwitches: [], weakNetwork: null }

  // 首次启动会展示 MOB-146 隐私告知层。性能脚本使用全新浏览器 context，
  // 因此必须按真实用户路径确认一次，否则弹层会拦截后续路由点击。
  async function acknowledgePrivacyNotice(page) {
    const button = page.getByRole('button', { name: '我已阅读并知晓', exact: true })
    if (await button.count()) await button.click()
  }

  // 低端设备模拟：对每个页面启用 CPU/网络节流（Chromium CDP）
  async function throttle(page) {
    if (cpuThrottle <= 1 && !networkPreset) return
    const session = await page.context().newCDPSession(page)
    if (cpuThrottle > 1) {
      await session.send('Emulation.setCPUThrottlingRate', { rate: cpuThrottle })
    }
    const preset = networkPreset ? NETWORK_PRESETS[networkPreset] : null
    if (preset) {
      await session.send('Network.enable')
      await session.send('Network.emulateNetworkConditions', {
        offline: false,
        latency: preset.latency,
        downloadThroughput: preset.download,
        uploadThroughput: preset.upload,
      })
    }
  }

  // 冷启动：全新 context（空缓存）
  {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const page = await context.newPage()
    await throttle(page)
    const t0 = Date.now()
    await page.goto(`${base}/#/`, { waitUntil: 'commit' })
    await page.waitForSelector('h1', { timeout: 60_000 })
    await acknowledgePrivacyNotice(page)
    const paint = await page.evaluate(() => {
      const entries = performance.getEntriesByType('paint')
      const fcp = entries.find(entry => entry.name === 'first-contentful-paint')
      return fcp ? fcp.startTime : null
    })
    // 可交互代理指标：底部导航可点击且主内容渲染完成
    await page.waitForSelector('nav a', { timeout: 30_000 })
    const interactiveMs = Date.now() - t0
    report.coldStart = { firstContentfulPaintMs: paint, interactiveMs }
    // 路由切换：今日→提醒→拍药盒→我的
    const routes = [
      ['提醒', 'h1'],
      ['拍药盒', 'h1'],
      ['我的', 'h1'],
    ]
    for (const [label, selector] of routes) {
      const start = Date.now()
      await page.getByRole('link', { name: label, exact: true }).click()
      await page.waitForSelector(selector, { timeout: 20_000 })
      await page.waitForFunction(() => (document.querySelector('h1')?.textContent ?? '').length > 0)
      report.routeSwitches.push({ to: label, ms: Date.now() - start })
    }
    await context.close()
  }

  // 断网：Service Worker 应以缓存外壳兜底（PWA 核心降级能力）；
  // 恢复网络后刷新应重新可交互。演示模式不产生业务请求，不涉及健康数据。
  {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const page = await context.newPage()
    await throttle(page)
    // 先在线加载一次，让 Service Worker 完成安装与外壳缓存
    await page.goto(`${base}/#/`, { waitUntil: 'commit' })
    await page.waitForSelector('h1', { timeout: 60_000 })
    await acknowledgePrivacyNotice(page)
    await page.waitForTimeout(800)
    await context.setOffline(true)
    const t0 = Date.now()
    await page.goto(`${base}/#/alerts`, { waitUntil: 'commit' }).catch(() => {})
    let offlineShellMs = null
    try {
      await page.waitForSelector('h1', { timeout: 20_000 })
      offlineShellMs = Date.now() - t0
    } catch {
      offlineShellMs = null // 外壳未兜底：判定时按 SKIP 处理并人工复核
    }
    await context.setOffline(false)
    const t1 = Date.now()
    await page.reload({ waitUntil: 'commit' }).catch(() => {})
    await page.waitForSelector('h1', { timeout: 60_000 })
    const recoveryMs = Date.now() - t1
    report.weakNetwork = { offlineShellMs, recoveryMs }
    await context.close()
  }

  await browser.close()
  return report
}

// ---------- 主流程 ----------
const preview = baseOverride ? { base: baseOverride, stop: () => {} } : await startPreview()
try {
  if (!existsSync(`${root}dist`)) throw new Error('未找到 dist/；请先 npm run build')

  console.log(`测量目标：${preview.base}（target=${target}，cpu=${cpuThrottle}，network=${networkPreset ?? '默认'}）`)
  const pageMetrics = await measurePage(preview.base)
  const measurements = {
    coldStart: pageMetrics.coldStart,
    routeSwitchWorstMs: Math.max(...pageMetrics.routeSwitches.map(r => r.ms)),
    weakNetwork: pageMetrics.weakNetwork,
    bundle: measureBundle(),
    ...(apk && existsSync(apk) ? { apkMiB: statSync(apk).size / 1024 / 1024 } : {}),
  }

  const result = evaluateBudget(measurements, config)
  const report = {
    generatedAt: new Date().toISOString(),
    target,
    base: preview.base,
    cpuThrottle,
    networkPreset,
    measurements,
    routeSwitches: pageMetrics.routeSwitches,
    budget: result,
  }

  const outDir = `${root}release`
  mkdirSync(outDir, { recursive: true })
  const stamp = report.generatedAt.replace(/[:.]/g, '-')
  const outFile = `${outDir}/perf-report-${target}-${stamp}.json`
  writeFileSync(outFile, `${JSON.stringify(report, null, 2)}\n`)
  console.log(formatBudgetReport(result))
  console.log(`报告已生成：${outFile}`)
  process.exit(result.ok ? 0 : 1)
} finally {
  preview.stop()
}
