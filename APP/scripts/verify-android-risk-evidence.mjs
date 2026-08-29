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
  'API/规则版本标识',
  '服务器地址形态',
  '测试数据与成员别名',
]

const REQUIRED_CASES = [
  'MOB173-RISK-01', 'MOB173-RISK-02', 'MOB173-RISK-03', 'MOB173-RISK-04',
  'MOB173-RISK-05', 'MOB173-RISK-06', 'MOB173-RISK-07', 'MOB173-RISK-08',
  'MOB173-RISK-09', 'MOB173-RISK-10',
]

const evidencePath = resolve(process.argv[2] ?? '../docs/testing/MOB-173-Android风险告警字段验收矩阵.md')
const text = await readFile(evidencePath, 'utf8')
const lines = text.split(/\r?\n/)
const failures = []

if (!text.includes('真机验收结论：通过')) {
  failures.push('未找到“真机验收结论：通过”；模板、浏览器或模拟器记录不得作为真机签收证据。')
}

for (const field of REQUIRED_METADATA) {
  const line = lines.find(candidate => candidate.startsWith(`| ${field} |`))
  if (!line || /待填写|待验收|未提供|不适用/.test(line)) failures.push(`缺少可复核元数据：${field}`)
}

for (const id of REQUIRED_CASES) {
  const line = lines.find(candidate => candidate.startsWith(`| ${id} |`))
  if (!line || !line.includes('通过') || /待填写|待验收|未执行|不通过/.test(line)) {
    failures.push(`用例 ${id} 没有合格的真机通过记录`)
  }
}

for (const phrase of ['字段完整', '信息不完整', '服务端合并/关联']) {
  if (!text.includes(phrase)) failures.push(`缺少风险审计路径证据：${phrase}`)
}

const attachmentSection = text.split('## 证据附件', 2)[1] ?? ''
const attachmentRows = attachmentSection
  .split(/\r?\n/)
  .filter(line => /^\| [^|]+ \| [^|]+ \| [^|]+ \|/.test(line) && !line.includes('附件 | 相对路径') && !line.includes('---'))
if (attachmentRows.length === 0 || attachmentRows.every(line => /待填写/.test(line))) {
  failures.push('至少归档一条脱敏风险列表/详情截图，并填写相对路径与 SHA-256')
}

if (failures.length > 0) {
  console.error('MOB-173 Android 风险告警字段真机证据门禁未通过：')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('MOB-173 Android 风险告警字段真机证据门禁通过。')
}
