import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const REQUIRED_METADATA = [
  '真机验收结论',
  '验收日期',
  '验收人',
  '设备型号',
  'Android 版本',
  'Android System WebView 版本',
  '中文 TTS 引擎与版本',
  'APK 或构建标识',
]

const REQUIRED_CASES = [
  'MOB150-VOICE-01', 'MOB150-VOICE-02', 'MOB150-VOICE-03', 'MOB150-VOICE-04',
  'MOB150-VOICE-05', 'MOB150-VOICE-06', 'MOB150-VOICE-07', 'MOB150-VOICE-08',
  'MOB150-VOICE-09', 'MOB150-VOICE-10', 'MOB150-VOICE-11', 'MOB150-VOICE-12',
  'MOB150-VOICE-13', 'MOB150-VOICE-14', 'MOB150-VOICE-15',
]

const evidencePath = resolve(process.argv[2] ?? '../docs/testing/MOB-150-Android真机语音助手验收记录.md')
const text = await readFile(evidencePath, 'utf8')
const failures = []

if (!text.includes('真机验收结论：通过')) {
  failures.push('未找到“真机验收结论：通过”；模板或待验收记录不得作为签收证据。')
}

for (const field of REQUIRED_METADATA) {
  const line = text.split(/\r?\n/).find(candidate => candidate.includes(`| ${field} |`) || candidate.startsWith(`| ${field} |`))
  if (!line || /待填写|待验收|不适用|未提供/.test(line)) failures.push(`缺少可复核元数据：${field}`)
}

for (const id of REQUIRED_CASES) {
  const line = text.split(/\r?\n/).find(candidate => candidate.startsWith(`| ${id} |`))
  if (!line || !line.includes('通过') || /待验收|未执行|浏览器|模拟器/.test(line)) {
    failures.push(`用例 ${id} 没有合格的真机通过记录`)
  }
}

if (failures.length > 0) {
  console.error('MOB-150 真机语音助手证据门禁未通过：')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('MOB-150 真机语音助手证据门禁通过。')
}
