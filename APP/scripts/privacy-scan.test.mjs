import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { scanDist } from './privacy-scan.mjs'

const dir = mkdtempSync(join(tmpdir(), 'mob142-scan-'))
try {
  // 干净 dist：白名单类型通过
  mkdirSync(join(dir, 'assets'), { recursive: true })
  writeFileSync(join(dir, 'index.html'), '<html></html>')
  writeFileSync(join(dir, 'assets', 'app.js'), 'console.log("ok")')
  const clean = scanDist(dir)
  assert.equal(clean.ok, true, JSON.stringify(clean.problems))

  // 禁止类型：.sqlite / .pem / .log
  writeFileSync(join(dir, 'dump.sqlite'), 'x')
  writeFileSync(join(dir, 'server.pem'), '-----BEGIN PRIVATE KEY-----')
  writeFileSync(join(dir, 'run.log'), 'x')
  const dirty = scanDist(dir)
  assert.equal(dirty.ok, false)
  assert.ok(dirty.problems.some(p => p.includes('dump.sqlite')))
  assert.ok(dirty.problems.some(p => p.includes('server.pem')))
  assert.ok(dirty.problems.some(p => p.includes('run.log')))

  // 未声明类型与体积超限
  rmSync(join(dir, 'dump.sqlite'))
  rmSync(join(dir, 'server.pem'))
  rmSync(join(dir, 'run.log'))
  writeFileSync(join(dir, 'unknown.bin'), 'x')
  const big = Buffer.alloc(4 * 1024 * 1024, 1)
  writeFileSync(join(dir, 'assets', 'big.js'), big)
  const flagged = scanDist(dir)
  assert.ok(flagged.problems.some(p => p.includes('未声明类型')))
  assert.ok(flagged.problems.some(p => p.includes('体积超限')))

  // dist 缺失时给出可行动错误
  const missing = scanDist(join(dir, 'not-exist'))
  assert.equal(missing.ok, false)
  assert.ok(missing.problems.some(p => p.includes('dist 不存在')))

  console.log('privacy scan tests passed')
} finally {
  rmSync(dir, { recursive: true, force: true })
}
