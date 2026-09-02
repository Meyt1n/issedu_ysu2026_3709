#!/usr/bin/env node
/**
 * MOB-148：移动端代码就绪的一键自动门禁。
 *
 * 该门禁串行执行移动端类型、单测、生产构建、响应式、隐私、Android 安全、
 * PWA 外壳、演示包、性能预算和受控发布校验。它不替代 Android 真机、PWA
 * 安装态、TalkBack、后端联调或维护者签收；这些证据必须在同一 APK/环境中补齐。
 *
 * 用法：
 *   npm run mobile:ready
 *   npm run mobile:ready -- --apk android/app/build/outputs/apk/debug/app-debug.apk --require-apk
 */
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const nodeCommand = process.execPath

function readArg(flag) {
  const index = args.indexOf(flag)
  return index >= 0 ? args[index + 1] ?? null : null
}

if (args.includes('--help') || args.includes('-h')) {
  console.log('用法：npm run mobile:ready [-- --apk <路径> [--require-apk]]')
  console.log('串行执行移动端自动门禁；不替代 Android/PWA 真机与后端联调验收。')
  process.exit(0)
}

const apkPath = readArg('--apk')
const requireApk = args.includes('--require-apk')
const failures = []

function run(label, command, commandArgs) {
  console.log(`\n=== ${label} ===`)
  const result = spawnSync(command, commandArgs, {
    cwd: appRoot,
    stdio: 'inherit',
    windowsHide: true,
    // Windows exposes npm as a .cmd shim; invoking that shim requires the
    // platform shell. All commands and arguments here are fixed local checks.
    shell: process.platform === 'win32' && command === npmCommand,
  })
  if (result.error) {
    failures.push(`${label}：${result.error.message}`)
    return false
  }
  if (result.status !== 0) {
    failures.push(`${label}：退出码 ${result.status ?? '未知'}`)
    return false
  }
  return true
}

run('类型检查', npmCommand, ['run', 'check'])
run('移动端全量回归测试', npmCommand, ['test', '--', '--reporter=dot'])
run('生产构建', npmCommand, ['run', 'build'])
run('横屏/折叠屏响应式审计', nodeCommand, ['scripts/audit-responsive-layout.mjs'])
run('隐私与敏感文件扫描', npmCommand, ['run', 'privacy:scan'])
run('Android 安全静态审计', npmCommand, ['run', 'audit:android-security'])
run('PWA 外壳与缓存边界审计', nodeCommand, ['scripts/audit-pwa.mjs'])

const demoArgs = ['scripts/mobile-demo-ready.mjs']
if (apkPath) demoArgs.push('--apk', apkPath)
if (requireApk) demoArgs.push('--require-apk')
run('演示包就绪检查', nodeCommand, demoArgs)

run('性能预算（浏览器 PWA）', nodeCommand, ['scripts/perf-budget.mjs'])
run('性能预算（低端设备/Slow 3G）', nodeCommand, [
  'scripts/perf-budget.mjs', '--cpu', '4', '--network', 'Slow 3G', '--target', 'low-end-sim',
])
run('性能预算库回归', nodeCommand, ['scripts/perf-budget-lib.test.mjs'])
run('受控发布校验器回归', nodeCommand, ['scripts/verify-controlled-release.test.mjs'])
run('Capacitor Android 资源同步', npmCommand, ['run', 'android:sync'])

if (failures.length > 0) {
  console.error('\n移动端一键就绪检查失败：')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exit(1)
}

console.log('\n移动端代码就绪自动门禁全部通过。')
console.log('剩余人工门禁：真实后端联调、PWA 安装态、Android 真机/折叠屏、TalkBack、通知/锁屏、升级回滚和维护者签收。')
