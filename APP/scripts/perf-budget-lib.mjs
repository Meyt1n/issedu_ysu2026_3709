/**
 * MOB-145：性能预算判定（纯函数，便于测试与复用）。
 *
 * 输入测量值与 perf-budget.config.json 的阈值，输出逐项 PASS/FAIL。
 * 只比较数值，不采集任何健康数据。
 */

export function evaluateBudget(measurements, thresholds) {
  const checks = []

  const push = (name, value, limit, unit, compare = 'max') => {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      checks.push({ name, value: null, limit, unit, status: 'SKIP' })
      return
    }
    const pass = compare === 'max' ? value <= limit : value >= limit
    checks.push({ name, value: Math.round(value * 100) / 100, limit, unit, status: pass ? 'PASS' : 'FAIL' })
  }

  push('冷启动首次内容绘制', measurements.coldStart?.firstContentfulPaintMs, thresholds.coldStart.firstContentfulPaintMs, 'ms')
  push('冷启动可交互', measurements.coldStart?.interactiveMs, thresholds.coldStart.interactiveMs, 'ms')
  push('路由切换（最慢）', measurements.routeSwitchWorstMs, thresholds.routeSwitchMs, 'ms')
  push('断网外壳可用（SW 缓存）', measurements.weakNetwork?.offlineShellMs, thresholds.weakNetwork.offlineShellMs, 'ms')
  push('断网恢复后可交互', measurements.weakNetwork?.recoveryMs, thresholds.weakNetwork.recoveryMs, 'ms')
  push('JS 体积（gzip）', measurements.bundle?.jsGzipTotalKiB, thresholds.bundle.jsGzipTotalKiB, 'KiB')
  push('CSS 体积（gzip）', measurements.bundle?.cssGzipTotalKiB, thresholds.bundle.cssGzipTotalKiB, 'KiB')
  push('图片体积', measurements.bundle?.imageTotalKiB, thresholds.bundle.imageTotalKiB, 'KiB')
  push('字体体积', measurements.bundle?.fontTotalKiB, thresholds.bundle.fontTotalKiB, 'KiB')
  push('单文件体积', measurements.bundle?.largestFileKiB, thresholds.bundle.singleFileKiB, 'KiB')
  if (typeof measurements.apkMiB === 'number') {
    push('APK 体积', measurements.apkMiB, thresholds.apkMiB, 'MiB')
  }

  const failed = checks.filter(check => check.status === 'FAIL')
  return {
    ok: failed.length === 0,
    checks,
    failedCount: failed.length,
  }
}

export function formatBudgetReport(result) {
  const lines = [`性能预算判定：${result.ok ? '全部通过' : `${result.failedCount} 项超预算`}`]
  for (const check of result.checks) {
    const mark = check.status === 'PASS' ? '✓' : check.status === 'FAIL' ? '✗' : '-'
    const valueText = check.value === null ? '跳过（无测量）' : `${check.value} ${check.unit}`
    lines.push(`  ${mark} ${check.name}：${valueText}（预算 ≤ ${check.limit} ${check.unit}）`)
  }
  return lines.join('\n')
}
