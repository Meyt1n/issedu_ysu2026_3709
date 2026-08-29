import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const REQUIRED_METADATA = [
  '真机验收结论',
  '验收日期',
  '验收人',
  '设备型号',
  'Android 版本',
  'ROM/系统版本',
  'Android System WebView 版本',
  'APK 或构建标识',
  'APK SHA-256',
  'PWA 浏览器与版本',
  'API/契约版本标识',
  '服务器地址形态',
  '合成数据与成员别名',
  '城市/区县编码',
]

const REQUIRED_CASES = [
  'MOB163-ENV-01', 'MOB163-ENV-02', 'MOB163-ENV-03', 'MOB163-ENV-04',
  'MOB163-ENV-05', 'MOB163-ENV-06', 'MOB163-ENV-07', 'MOB163-ENV-08',
  'MOB163-ENV-09', 'MOB163-ENV-10', 'MOB163-ENV-11', 'MOB163-ENV-12',
]

const evidencePath = resolve(process.argv[2] ?? '../docs/testing/MOB-163-Android-PWA环境行动卡联调验收矩阵.md')
const text = await readFile(evidencePath, 'utf8')
const lines = text.split(/\r?\n/)
const failures = []

const conclusionLine = lines.find(candidate => candidate.startsWith('| 真机验收结论 |'))
if (!conclusionLine || !conclusionLine.includes('真机验收结论：通过')) {
  failures.push('环境信息未记录“真机验收结论：通过”；模板、浏览器或模拟器记录不得作为真机签收证据。')
}

for (const field of REQUIRED_METADATA) {
  const line = lines.find(candidate => candidate.startsWith(`| ${field} |`))
  if (!line || /待填写|待验收|未提供|不适用/.test(line)) failures.push(`缺少可复核元数据：${field}`)
}

for (const id of REQUIRED_CASES) {
  const line = lines.find(candidate => candidate.startsWith(`| ${id} |`))
  if (!line || !line.includes('通过') || /待填写|待验收|未执行|不通过/.test(line)) {
    failures.push(`用例 ${id} 没有合格的真机/PWA 通过记录`)
  }
}

for (const phrase of ['已授权成员', '未授权环境标签', '城市编码缺失', '访问目的不匹配', '超时', '限速', '上游失败', '旧缓存', '去重', '精确坐标']) {
  if (!text.includes(phrase)) failures.push(`缺少环境行动卡联调路径证据：${phrase}`)
}

const attachmentSection = text.split('## 证据附件', 2)[1] ?? ''
const attachmentRows = attachmentSection
  .split(/\r?\n/)
  .filter(line => /^\| [^|]+ \| [^|]+ \| [^|]+ \|/.test(line) && !line.includes('附件 | 相对路径') && !line.includes('---'))
if (attachmentRows.length === 0 || attachmentRows.every(line => /待填写/.test(line))) {
  failures.push('至少归档一条脱敏 Android/PWA 截图或录屏附件，并填写相对路径与 SHA-256')
}

const completedCaseRows = lines.filter(line => /^\| MOB163-ENV-\d+ \|/.test(line) && line.includes('通过'))
if (completedCaseRows.some(line => /(精确坐标|真实姓名|token|完整响应)/i.test(line))) {
  failures.push('通过用例记录仍出现禁止提交的精确坐标、真实姓名、token 或完整响应')
}

if (failures.length > 0) {
  console.error('MOB-163 Android/PWA 环境行动卡真机证据门禁未通过：')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('MOB-163 Android/PWA 环境行动卡真机证据门禁通过。')
}
