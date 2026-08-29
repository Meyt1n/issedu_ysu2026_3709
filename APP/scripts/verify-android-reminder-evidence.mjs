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
  '通知权限',
  '锁屏通知隐私',
  '电池优化',
  '后台自启动',
  '勿扰模式',
]

const REQUIRED_CASES = [
  'MOB172-REM-01', 'MOB172-REM-02', 'MOB172-REM-03', 'MOB172-REM-04',
  'MOB172-REM-05', 'MOB172-REM-06', 'MOB172-REM-07', 'MOB172-REM-08',
  'MOB172-REM-09', 'MOB172-REM-10', 'MOB172-REM-11', 'MOB172-REM-12',
  'MOB172-PRIV-01', 'MOB172-PRIV-02',
]

const evidencePath = resolve(process.argv[2] ?? '../docs/testing/MOB-172-Android计划提醒验收矩阵.md')
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
  if (!line || /待填写|待验收|未执行/.test(line) || !/(通过|未到达|不适用)/.test(line)) {
    failures.push(`用例 ${id} 缺少可复核结果；必须记录通过、未到达或不适用及原因`)
  }
}

for (const id of ['MOB172-PRIV-01', 'MOB172-PRIV-02']) {
  const line = lines.find(candidate => candidate.startsWith(`| ${id} |`))
  if (line && !line.includes('通过')) failures.push(`隐私用例 ${id} 未通过；锁屏/通知栏不得展示药品名、剂量或成员姓名`)
}

const attachmentSection = text.split('## 证据附件', 2)[1] ?? ''
const attachmentRows = attachmentSection
  .split(/\r?\n/)
  .filter(line => /^\| [^|]+ \| [^|]+ \| [^|]+ \|/.test(line) && !line.includes('附件 | 相对路径'))
if (attachmentRows.length === 0 || attachmentRows.every(line => /待填写/.test(line))) {
  failures.push('至少归档一条脱敏截图或录屏附件，并填写相对路径与 SHA-256')
}

if (failures.length > 0) {
  console.error('MOB-172 Android 计划提醒真机证据门禁未通过：')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('MOB-172 Android 计划提醒真机证据门禁通过。')
}
