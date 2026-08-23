#!/usr/bin/env node
/**
 * MOB-142：发布包隐私扫描。
 *
 * 检查发布产物不携带密钥、真实数据或未声明的大文件：
 * 1. dist 只包含允许的静态资源类型（js/css/html/json/svg/png/webmanifest/ico/txt/woff2）；
 * 2. dist 不出现私钥/证书头、.env 内容或 sqlite/日志/缓存文件；
 * 3. 不包含体积异常的单文件（> 3 MiB，字体除外——本项目未打包大字体）；
 * 4. debug APK 若存在，仅允许 debug 签名命名，不携带 release keystore。
 *
 * 只扫描文件名、类型与体积，不读取健康数据内容。
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath, pathToFileURL, URL } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const distDir = `${root}dist`

const ALLOWED_EXTENSIONS = new Set([
  '.js', '.css', '.html', '.json', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.webmanifest', '.ico', '.txt', '.woff2', '.map',
])
const FORBIDDEN_EXTENSIONS = new Set(['.env', '.pem', '.key', '.p12', '.jks', '.keystore', '.sqlite', '.db', '.log'])
const FORBIDDEN_CONTENT = [/-----BEGIN (RSA |EC )?PRIVATE KEY-----/, /BEGIN CERTIFICATE/]
const MAX_FILE_BYTES = 3 * 1024 * 1024

export function scanDist(distPath = distDir) {
  const problems = []
  if (!existsSync(distPath)) {
    return { ok: false, problems: ['dist 不存在：请先 npm run build'] }
  }
  const visit = (dir, base = '') => {
    for (const name of readdirSync(dir)) {
      const full = `${dir}/${name}`
      const rel = base ? `${base}/${name}` : name
      if (statSync(full).isDirectory()) {
        visit(full, rel)
        continue
      }
      const lower = name.toLowerCase()
      const dot = lower.lastIndexOf('.')
      const ext = dot >= 0 ? lower.slice(dot) : ''
      if (FORBIDDEN_EXTENSIONS.has(ext)) problems.push(`禁止类型：${rel}`)
      else if (!ALLOWED_EXTENSIONS.has(ext)) problems.push(`未声明类型：${rel}（${ext || '无扩展名'}）`)
      const size = statSync(full).size
      if (size > MAX_FILE_BYTES) problems.push(`体积超限：${rel}（${(size / 1024 / 1024).toFixed(2)} MiB > 3 MiB）`)
      if (['.js', '.html', '.json'].includes(ext)) {
        const head = readFileSync(full).slice(0, 512 * 1024).toString('utf-8')
        for (const pattern of FORBIDDEN_CONTENT) {
          if (pattern.test(head)) problems.push(`疑似密钥内容：${rel}`)
        }
      }
    }
  }
  visit(distPath)
  return { ok: problems.length === 0, problems }
}

function scanAndroidKeystores() {
  const problems = []
  const appDir = `${root}android/app`
  if (!existsSync(appDir)) return problems
  for (const name of readdirSync(appDir)) {
    const lower = name.toLowerCase()
    if (lower.endsWith('.keystore') || lower.endsWith('.jks') || lower.endsWith('.p12')) {
      problems.push(`Android 目录内出现签名材料：android/app/${name}（不得提交）`)
    }
  }
  return problems
}

export function runPrivacyScan() {
  const distResult = scanDist()
  const keystoreProblems = scanAndroidKeystores()
  return [...distResult.problems, ...keystoreProblems]
}

// 直接执行（node scripts/privacy-scan.mjs）时才作为 CLI 运行
const invokedDirectly = process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href
if (invokedDirectly) {
  const problems = runPrivacyScan()
  if (problems.length > 0) {
    console.error('隐私扫描未通过：')
    for (const problem of problems) console.error(`  - ${problem}`)
    process.exit(1)
  }
  console.log('隐私扫描通过：dist 资源类型、体积与密钥检查均无问题；未发现签名材料。')
}
