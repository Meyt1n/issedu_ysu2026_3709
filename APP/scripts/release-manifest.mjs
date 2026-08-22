#!/usr/bin/env node
/**
 * MOB-142：发布产物清单与哈希。
 *
 * 用法：
 *   node scripts/release-manifest.mjs [--apk <path/to/app-debug.apk>] [--out <dir>]
 *
 * 输出 JSON 清单：版本号（package.json）、构建信息（由 vite 注入进 dist，
 * 从 dist 资产里回读校验）、源码提交、生成时间，以及每个产物的 SHA-256。
 * 清单用于发布签收与回滚定位：任意产物可凭哈希反查源码提交。
 * 不含任何健康数据、密钥或服务器地址。
 */
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

const args = process.argv.slice(2)
function argOf(flag) {
  const index = args.indexOf(flag)
  return index >= 0 && args[index + 1] ? args[index + 1] : null
}

const root = fileURLToPath(new URL('..', import.meta.url))
const distDir = `${root}dist`
const outDir = argOf('--out') ?? `${root}release`
const apk = argOf('--apk')

if (!existsSync(distDir)) {
  console.error('未找到 dist/；请先 npm run build（或 android:sync）。')
  process.exit(1)
}

function sha256(filePath) {
  return createHash('sha256').update(readFileSync(filePath)).digest('hex')
}

function gitCommit() {
  const override = process.env.APP_BUILD_COMMIT
  if (override) return override
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
  } catch {
    return 'unknown'
  }
}

function walk(dir, base = '') {
  const out = []
  for (const name of readdirSync(dir)) {
    const full = `${dir}/${name}`
    const rel = base ? `${base}/${name}` : name
    if (statSync(full).isDirectory()) out.push(...walk(full, rel))
    else out.push({ rel, full })
  }
  return out
}

const pkg = JSON.parse(readFileSync(`${root}package.json`, 'utf-8'))

// 从 dist 里回读构建期注入的提交哈希，验证"清单 ↔ 产物"一致
function findInjectedCommit(commit) {
  if (!commit || commit === 'unknown') return null
  for (const file of walk(distDir)) {
    if (!file.rel.endsWith('.js')) continue
    if (readFileSync(file.full, 'utf-8').includes(commit)) return commit
  }
  return null
}

const artifacts = [
  ...walk(distDir).map(file => ({
    path: `dist/${file.rel}`,
    bytes: statSync(file.full).size,
    sha256: sha256(file.full),
  })),
]

if (apk) {
  if (!existsSync(apk)) {
    console.error(`未找到 APK：${apk}`)
    process.exit(1)
  }
  artifacts.push({ path: apk.replace(root, '').replace(/^[\\/]/, ''), bytes: statSync(apk).size, sha256: sha256(apk) })
}

const sourceCommit = gitCommit()
const injectedCommit = findInjectedCommit(sourceCommit)
const manifest = {
  generatedAt: new Date().toISOString(),
  version: pkg.version,
  sourceCommit,
  injectedCommit,
  commitConsistent: injectedCommit === null ? 'not-found' : injectedCommit === sourceCommit,
  artifactCount: artifacts.length,
  artifacts,
}

mkdirSync(outDir, { recursive: true })
const stamp = manifest.generatedAt.replace(/[:.]/g, '-')
const outFile = `${outDir}/manifest-${manifest.version}-${stamp}.json`
writeFileSync(outFile, `${JSON.stringify(manifest, null, 2)}\n`)

console.log(`清单已生成：${outFile}`)
console.log(`版本 ${manifest.version} · 源码提交 ${manifest.sourceCommit} · 产物提交一致性 ${manifest.commitConsistent} · 产物 ${artifacts.length} 个`)
for (const artifact of artifacts.slice(0, 5)) {
  console.log(`  ${artifact.path}  ${artifact.sha256.slice(0, 16)}…  ${(artifact.bytes / 1024).toFixed(1)} KiB`)
}
if (artifacts.length > 5) console.log(`  … 共 ${artifacts.length} 个产物`)
