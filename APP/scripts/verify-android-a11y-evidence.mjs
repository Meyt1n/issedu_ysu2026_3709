import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const REQUIRED_METADATA = [
  '设备型号',
  'Android 版本',
  'Android System WebView 版本',
  'TalkBack 版本',
  '中文 TTS 引擎与版本',
  'APK SHA-256',
  '验收日期',
  '验收人',
]

const REQUIRED_CASES = [
  'MOB141-AND-01', 'MOB141-AND-02', 'MOB141-AND-03', 'MOB141-AND-04',
  'MOB141-AND-05', 'MOB141-AND-06', 'MOB141-AND-07', 'MOB141-AND-08',
  'MOB141-AND-09', 'MOB141-AND-10', 'MOB141-AND-11', 'MOB141-AND-12',
]

const evidencePath = resolve(process.argv[2] ?? '../docs/testing/MOB-141-Android真机无障碍验收记录.md')
const text = await readFile(evidencePath, 'utf8')
const failures = []

if (!text.includes('真机验收结论：通过')) {
  failures.push('未找到“真机验收结论：通过”；模板或待验收记录不得作为签收证据。')
}

for (const field of REQUIRED_METADATA) {
  const line = text.split(/\r?\n/).find(candidate => candidate.startsWith(`| ${field} |`))
  if (!line || /待填写|不适用|未提供/.test(line)) failures.push(`缺少可复核元数据：${field}`)
}

for (const id of REQUIRED_CASES) {
  const line = text.split(/\r?\n/).find(candidate => candidate.startsWith(`| ${id} |`))
  if (!line || !line.includes('通过') || /待验收|未执行|浏览器|模拟器/.test(line)) {
    failures.push(`用例 ${id} 没有合格的真机通过记录`)
  }
}

if (failures.length > 0) {
  console.error('MOB-141 真机无障碍证据门禁未通过：')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('MOB-141 真机无障碍证据门禁通过。')
}
