#!/usr/bin/env node
/**
 * MOB-170：手机演示包的本地、只读就绪检查。
 *
 * 该脚本不启动服务、不访问网络，也不读取健康数据。它只检查生产构建的
 * PWA 外壳、Service Worker 的隐私边界，以及可选的本机 APK 文件是否存在。
 * APK 仍然是本机临时产物，不会因为运行本检查而被复制或提交到仓库。
 *
 * 用法：
 *   npm run build
 *   npm run demo:ready
 *   npm run demo:ready -- --apk android/app/build/outputs/apk/debug/app-debug.apk --require-apk
 */
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const appRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const distRoot = path.join(appRoot, 'dist')
const args = process.argv.slice(2)

function readArg(flag) {
  const index = args.indexOf(flag)
  return index >= 0 ? args[index + 1] ?? null : null
}

if (args.includes('--help') || args.includes('-h')) {
  console.log('用法：npm run demo:ready [-- --apk <路径> [--require-apk]]')
  console.log('只读检查 PWA 外壳、离线缓存边界和可选 APK；不会访问网络或读取健康数据。')
  process.exit(0)
}

const apkArgument = readArg('--apk')
const requireApk = args.includes('--require-apk')
const failures = []
const checks = []

function check(condition, message, detail = '') {
  if (condition) checks.push(`通过：${message}`)
  else failures.push(`${message}${detail ? `（${detail}）` : ''}`)
}

function readUtf8(filePath, label) {
  try {
    return readFileSync(filePath, 'utf8')
  } catch {
    failures.push(`缺少${label}：${path.relative(appRoot, filePath)}`)
    return ''
  }
}

check(existsSync(distRoot), '已找到 PWA 生产构建目录', '请先运行 npm run build')

const indexPath = path.join(distRoot, 'index.html')
const manifestPath = path.join(distRoot, 'manifest.webmanifest')
const swPath = path.join(distRoot, 'sw.js')
const indexSource = readUtf8(indexPath, '应用入口')
const swSource = readUtf8(swPath, 'Service Worker')
const manifestSource = readUtf8(manifestPath, 'Web App Manifest')

check(existsSync(indexPath), '应用入口存在')
check(existsSync(manifestPath), 'Web App Manifest 存在')
check(existsSync(swPath), 'Service Worker 存在')
check(indexSource.includes('manifest.webmanifest'), '应用入口声明了 PWA Manifest')

let manifest = null
try {
  manifest = JSON.parse(manifestSource)
} catch {
  failures.push('Web App Manifest 不是有效 JSON')
}

if (manifest) {
  check(manifest.start_url === '/', 'Manifest start_url 为应用外壳 /')
  check(manifest.scope === '/', 'Manifest scope 为应用外壳 /')
  check(manifest.display === 'standalone', 'Manifest display 为 standalone')
  check(manifest.orientation === 'portrait', 'Manifest orientation 为 portrait')
  check(typeof manifest.description === 'string' && manifest.description.includes('教学演示'), 'Manifest 明确教学演示边界')
  check(Array.isArray(manifest.icons) && manifest.icons.length >= 4, 'Manifest 至少声明四个图标资源')

  for (const icon of manifest.icons ?? []) {
    const iconPath = path.join(distRoot, String(icon.src ?? '').replace(/^\//, ''))
    check(existsSync(iconPath), `图标资源存在：${icon.src ?? '(未命名)'}`)
  }
}

const shellEntries = [...swSource.matchAll(/['"](\/[^'"]+)['"]/g)].map(match => match[1])
const shellAssets = [...new Set(shellEntries.filter(entry => !entry.startsWith('/api') && !entry.startsWith('/health')))]
check(shellAssets.length >= 4, 'Service Worker 声明了应用外壳预缓存清单')
for (const asset of shellAssets) {
  const assetPath = path.join(distRoot, asset === '/' ? 'index.html' : asset.slice(1))
  check(existsSync(assetPath), `外壳资源存在：${asset}`)
}

check(swSource.includes("url.pathname.startsWith('/api') || url.pathname.startsWith('/health')"), 'Service Worker 不缓存 /api 与 /health')
check(swSource.includes('offlineShellResponse'), 'Service Worker 有隐私安全的离线外壳回退')
check(swSource.includes("request.mode === 'navigate'"), '页面导航采用独立离线回退策略')
check(swSource.includes("request.method !== 'GET'"), '非 GET 请求不会进入缓存逻辑')
check(swSource.includes("url.origin !== self.location.origin"), '跨源请求不会进入缓存逻辑')

let apkSummary = '未检查 APK（PWA 演示路径）'
if (requireApk && !apkArgument) {
  failures.push('已要求 APK，但没有提供 --apk 路径；请先执行 scripts/build-apk.ps1')
}
if (apkArgument) {
  const apkPath = path.resolve(process.cwd(), apkArgument)
  const apkExists = existsSync(apkPath)
  check(apkExists, 'APK 文件存在', apkPath)
  if (apkExists) {
    const size = statSync(apkPath).size
    const isApk = path.extname(apkPath).toLowerCase() === '.apk'
    check(isApk, 'APK 路径扩展名为 .apk', path.basename(apkPath))
    check(size > 0, 'APK 文件非空', `${size} bytes`)
    if (isApk && size > 0) {
      const sha256 = createHash('sha256').update(readFileSync(apkPath)).digest('hex')
      apkSummary = `${path.relative(appRoot, apkPath)} · ${size} bytes · SHA-256 ${sha256}`
    }
  }
}

if (failures.length > 0) {
  console.error('手机演示包就绪检查失败：')
  for (const failure of failures) console.error(`- ${failure}`)
  console.error('修复后重跑：npm run build && npm run demo:ready')
  process.exit(1)
}

console.log('手机演示包就绪检查通过（本地只读，无网络访问）。')
for (const item of checks) console.log(`- ${item}`)
console.log(`- APK：${apkSummary}`)
console.log('演示入口：默认选择「演示模式」，Today → 健康资讯 → 带着问题问助手 → 返回今日任务。')
console.log('边界提醒：演示数据为虚构本地夹具；离线时只保留应用外壳，不展示或缓存旧健康数据。')
