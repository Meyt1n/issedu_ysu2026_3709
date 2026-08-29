#!/usr/bin/env node
/**
 * MOB-174：横屏与折叠屏布局的静态预检。
 *
 * 该检查不模拟或伪造真机截图，只确认响应式契约仍存在：页面容器可收缩、
 * 横向溢出有边界、底部导航和内容保留安全区、低高度横屏有独立间距，且
 * 支持 CSS Foldables API 的 WebView 有铰链分段兜底。真机走查仍需设备持有人签收。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const appRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const stylePath = path.join(appRoot, 'src', 'style.css')
const tabBarPath = path.join(appRoot, 'src', 'components', 'AppTabBar.vue')
const styleSource = readFileSync(stylePath, 'utf8')
const tabBarSource = readFileSync(tabBarPath, 'utf8')
const failures = []

function assert(condition, message) {
  if (!condition) failures.push(message)
}

assert(styleSource.includes('--hct-bottom-clearance: 116px'), '缺少默认底部导航留白变量')
assert(styleSource.includes('width: 100%;\n  min-width: 0;\n  max-width: 100%;'), 'html/body/#app 未声明可收缩宽度边界')
assert(styleSource.includes('overflow-x: clip;'), '页面未声明 overflow-x: clip 横向溢出边界')
assert(styleSource.includes('width: 100%;\n  max-width: 560px;'), '.screen 未声明占满可用宽度')
assert(styleSource.includes('calc(var(--hct-bottom-clearance) + var(--hct-safe-area-bottom))'), '.screen 未为底部导航保留安全区')
assert(styleSource.includes('@media (orientation: landscape)'), '缺少横屏响应式规则')
assert(styleSource.includes('@media (orientation: landscape) and (max-height: 560px)'), '缺少低高度横屏规则')
assert(styleSource.includes('@media (horizontal-viewport-segments: 2)'), '缺少折叠屏双分段安全边距规则')
assert(styleSource.includes('.screen > *') && styleSource.includes('min-width: 0;'), '横屏页面子项未统一允许收缩')
assert(styleSource.includes('.section-link { white-space: normal;'), '横屏区块链接仍可能强制单行溢出')
assert(tabBarSource.includes('var(--hct-safe-area-bottom)'), '底部导航未使用安全区变量')
assert(!/width\s*:\s*100vw\b/.test(styleSource), '发现 100vw 宽度声明，可能制造横向滚动')

if (failures.length) {
  console.error('响应式布局预检失败：')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exit(1)
}

console.log('响应式布局预检通过：横屏、低高度横屏与折叠屏分段规则均存在。')
console.log('静态边界通过：页面与子项可收缩、横向溢出受控、底部导航保留安全区。')
console.log('注意：该命令不替代 Android 真机/折叠屏截图、TalkBack 或状态保持验收。')
