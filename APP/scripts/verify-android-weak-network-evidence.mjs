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
  'API/错误契约版本标识',
  '合成数据与成员别名',
  '弱网注入与网络状态',
  '屏幕与辅助设置',
]

const REQUIRED_CASES = [
  'MOB171-NET-01', 'MOB171-NET-02', 'MOB171-NET-03', 'MOB171-NET-04',
  'MOB171-NET-05', 'MOB171-NET-06', 'MOB171-NET-07', 'MOB171-NET-08',
  'MOB171-NET-09', 'MOB171-NET-10', 'MOB171-NET-11', 'MOB171-NET-12',
]

const evidencePath = resolve(process.argv[2] ?? '../docs/testing/MOB-171-Android-PWA弱网列表验收矩阵.md')
const text = await readFile(evidencePath, 'utf8')
const lines = text.split(/\r?\n/)
const failures = []

const conclusionLine = lines.find(candidate => candidate.startsWith('| 真机验收结论 |'))
if (!conclusionLine || !conclusionLine.includes('真机验收结论：通过')) {
  failures.push('环境信息未记录“真机验收结论：通过”；模板、浏览器或模拟器不得作为真机签收证据。')
}

for (const field of REQUIRED_METADATA) {
  const line = lines.find(candidate => candidate.startsWith(`| ${field} |`))
  if (!line || /待填写|待验收|未提供|不适用/.test(line)) failures.push(`缺少可复核元数据：${field}`)
}

for (const id of REQUIRED_CASES) {
  const line = lines.find(candidate => candidate.startsWith(`| ${id} |`))
  if (!line || !line.includes('通过') || /待填写|待验收|未执行|不通过/.test(line)) {
    failures.push(`用例 ${id} 没有合格的 Android/PWA 通过记录`)
  }
}

for (const phrase of ['骨架屏', '减少动效', '连接超时', '服务端处理慢', '确实没有数据', '部分数据', '不发起重复请求', 'TalkBack', '加载→失败→成功', '伪造示例数据']) {
  if (!text.includes(phrase)) failures.push(`缺少弱网列表验收路径证据：${phrase}`)
}

const completedCaseRows = lines.filter(line => /^\| MOB171-NET-\d+ \|/.test(line) && line.includes('通过'))
if (completedCaseRows.some(line => /(真实姓名|token|完整响应|公网地址)/i.test(line))) {
  failures.push('通过用例记录仍出现禁止提交的真实姓名、token、公网地址或完整响应')
}

const attachmentSection = text.split('## 证据附件', 2)[1] ?? ''
const attachmentRows = attachmentSection
  .split(/\r?\n/)
  .filter(line => /^\| [^|]+ \| [^|]+ \| [^|]+ \|/.test(line) && !line.includes('附件 | 相对路径') && !line.includes('---'))
if (attachmentRows.length === 0 || attachmentRows.every(line => /待填写/.test(line))) {
  failures.push('至少归档一条脱敏 Android/PWA 弱网截图或录屏附件，并填写相对路径与 SHA-256')
}

if (failures.length > 0) {
  console.error('MOB-171 Android/PWA 弱网列表真机证据门禁未通过：')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('MOB-171 Android/PWA 弱网列表真机证据门禁通过。')
}
