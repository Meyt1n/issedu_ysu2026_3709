import assert from 'node:assert/strict'

import { evaluateBudget, formatBudgetReport } from './perf-budget-lib.mjs'

const thresholds = {
  coldStart: { firstContentfulPaintMs: 3000, interactiveMs: 5000 },
  routeSwitchMs: 1200,
  weakNetwork: { offlineShellMs: 6000, recoveryMs: 15000 },
  bundle: { jsGzipTotalKiB: 260, cssGzipTotalKiB: 40, imageTotalKiB: 900, fontTotalKiB: 20, singleFileKiB: 3072 },
  apkMiB: 8,
}

// 全部达标 → ok
const pass = evaluateBudget(
  {
    coldStart: { firstContentfulPaintMs: 900, interactiveMs: 1800 },
    routeSwitchWorstMs: 400,
    weakNetwork: { offlineShellMs: 1200, recoveryMs: 3000 },
    bundle: { jsGzipTotalKiB: 120, cssGzipTotalKiB: 15, imageTotalKiB: 300, fontTotalKiB: 0, largestFileKiB: 130 },
    apkMiB: 4.4,
  },
  thresholds,
)
assert.equal(pass.ok, true)
assert.equal(pass.failedCount, 0)

// 单项超预算 → ok=false 且指出超限项
const fail = evaluateBudget(
  {
    coldStart: { firstContentfulPaintMs: 900, interactiveMs: 9500 },
    routeSwitchWorstMs: 400,
    weakNetwork: { offlineShellMs: 1200, recoveryMs: 3000 },
    bundle: { jsGzipTotalKiB: 300, cssGzipTotalKiB: 15, imageTotalKiB: 300, fontTotalKiB: 0, largestFileKiB: 130 },
  },
  thresholds,
)
assert.equal(fail.ok, false)
assert.equal(fail.failedCount, 2)
const failedNames = fail.checks.filter(c => c.status === 'FAIL').map(c => c.name)
assert.ok(failedNames.includes('冷启动可交互'))
assert.ok(failedNames.includes('JS 体积（gzip）'))
assert.equal(failedNames.includes('断网恢复后可交互'), false) // 该项达标

// 缺失测量 → SKIP 不判失败
const partial = evaluateBudget({ coldStart: { firstContentfulPaintMs: 800 } }, thresholds)
assert.equal(partial.ok, true)
assert.equal(partial.checks.filter(c => c.status === 'SKIP').length >= 5, true)

// APK 未提供时不产生检查项
assert.ok(!pass.checks.some(c => c.name === 'APK 体积' && c.value === null))

const text = formatBudgetReport(fail)
assert.ok(text.includes('2 项超预算'))
assert.ok(text.includes('✗'))
assert.ok(text.includes('✓'))

console.log('perf budget lib tests passed')
