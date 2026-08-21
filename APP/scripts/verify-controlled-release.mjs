import { createHash } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const requiredKeys = [
  'release_id', 'environment', 'server_base_url', 'server_commit', 'app_commit',
  'api_version', 'pwa_shell_version', 'android_version', 'synthetic_seed_sha256',
  'device', 'evidence',
]
const forbiddenKeyPattern = /(secret|password|token|credential|private.?key|cookie)/i
const sha256Pattern = /^[a-f0-9]{64}$/i
const commitPattern = /^[a-f0-9]{7,64}$/i
const placeholderPattern = /(<[^>]+>|example|placeholder|replace.?me|todo|changeme)/i

export function validateControlledReleaseRecord(record) {
  const errors = []
  if (!record || typeof record !== 'object' || Array.isArray(record)) return ['记录必须是 JSON 对象']
  for (const key of requiredKeys) {
    if (!(key in record) || record[key] === '' || record[key] == null) errors.push(`缺少必填字段：${key}`)
  }
  for (const [key, value] of Object.entries(record)) {
    if (forbiddenKeyPattern.test(key)) errors.push(`禁止在发布记录中写入敏感字段：${key}`)
    if (typeof value === 'string' && placeholderPattern.test(value)) errors.push(`字段不能使用占位符：${key}`)
  }
  if (record.environment !== 'controlled-demo') errors.push('environment 必须为 controlled-demo')
  if (typeof record.server_base_url !== 'string' || !record.server_base_url.startsWith('https://')) {
    errors.push('server_base_url 必须是 HTTPS，且不得是开发代理或明文 HTTP')
  }
  for (const key of ['server_commit', 'app_commit']) {
    if (typeof record[key] !== 'string' || !commitPattern.test(record[key])) errors.push(`${key} 必须是 Git 提交哈希`)
  }
  if (typeof record.synthetic_seed_sha256 !== 'string' || !sha256Pattern.test(record.synthetic_seed_sha256)) {
    errors.push('synthetic_seed_sha256 必须是合成种子文件的 SHA-256')
  }
  if (!record.synthetic_data || record.synthetic_data.is_real !== false || record.synthetic_data.label !== '演示') {
    errors.push('synthetic_data 必须明确声明 is_real=false 且 label=演示')
  }
  if (!record.device || !['PWA', 'Android WebView'].includes(record.device.target)) {
    errors.push('device.target 必须为 PWA 或 Android WebView')
  }
  if (!record.evidence || !Array.isArray(record.evidence.scenarios) || record.evidence.scenarios.length === 0) {
    errors.push('evidence.scenarios 必须包含至少一个已执行场景')
  }
  return errors
}

export function fingerprint(record) {
  const payload = JSON.stringify({
    release_id: record.release_id,
    server_commit: record.server_commit,
    app_commit: record.app_commit,
    api_version: record.api_version,
    pwa_shell_version: record.pwa_shell_version,
    android_version: record.android_version,
    synthetic_seed_sha256: record.synthetic_seed_sha256,
  })
  return createHash('sha256').update(payload).digest('hex')
}

function readArgument(flag) {
  const index = process.argv.indexOf(flag)
  return index >= 0 ? process.argv[index + 1] : undefined
}

function main() {
  const recordPath = readArgument('--record')
  if (!recordPath) throw new Error('用法：node scripts/verify-controlled-release.mjs --record <未提交的发布记录.json>')
  const absolutePath = path.resolve(process.cwd(), recordPath)
  const record = JSON.parse(fs.readFileSync(absolutePath, 'utf8'))
  const errors = validateControlledReleaseRecord(record)
  if (errors.length) throw new Error(`受控发布记录校验失败：\n- ${errors.join('\n- ')}`)
  console.log(JSON.stringify({
    status: 'passed',
    releaseId: record.release_id,
    target: record.device.target,
    fingerprint: fingerprint(record),
    evidenceCount: record.evidence.scenarios.length,
  }, null, 2))
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main()