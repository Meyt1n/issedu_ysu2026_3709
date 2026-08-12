import { readdir, readFile } from 'node:fs/promises'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const sourceRoot = fileURLToPath(new URL('./src/', import.meta.url))
const sourceExtensions = new Set(['.css', '.jsx', '.tsx'])
const forbiddenPatterns = [
  /https?:\/\//i,
  /\b(fetch|axios|XMLHttpRequest)\s*\(/,
]

async function collectFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) files.push(...await collectFiles(path))
    else if (sourceExtensions.has(extname(entry.name))) files.push(path)
  }
  return files
}

const files = await collectFiles(sourceRoot)
const source = (await Promise.all(files.map(path => readFile(path, 'utf8')))).join('\n')
const violations = forbiddenPatterns.flatMap(pattern => source.match(pattern) ?? [])
if (violations.length > 0) {
  throw new Error(`HCT407_OFFLINE_SOURCE_CHECK_FAILED: ${violations.join(', ')}`)
}

const requiredSnippets = [
  'demo-disclaimer',
  '模型实验室',
  '证据与分析详情',
  '当前未接入真实 API',
  '不代表已完成生产能力',
  '教学演示 · 非实时生成',
]
const missing = requiredSnippets.filter(snippet => !source.includes(snippet))
if (missing.length > 0) {
  throw new Error(`HCT407_REQUIRED_BOUNDARY_TEXT_MISSING: ${missing.join(', ')}`)
}

console.log(`HCT-407 static verification passed: ${files.length} source files checked; local assets only; no direct API/network calls.`)
