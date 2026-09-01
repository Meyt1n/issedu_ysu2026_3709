/** Family-facing local runtime lights for the big-screen / overview rail. */

const HIDDEN_UNAVAILABLE = new Set(['llm-cloud', 'hct201-formal-drug-set'])

const CAPABILITY_LABELS: Record<string, string> = {
  llm: '本地大模型',
  'local-assistant': '本地助手',
  'vision-inference': '视觉推理',
  'vision-task': '视觉识别任务',
  'knowledge-store': '本地知识库',
  'review-task': '人工复核',
  'external-web': '受控联网搜索',
  'face-recognition-local': '本机人脸识别',
  'manual-health-event': '健康事件录入',
  'household-member': '家庭成员档案',
  'field-authorization': '字段授权',
}

const PREFERRED_ON = [
  'llm',
  'local-assistant',
  'vision-inference',
  'vision-task',
  'knowledge-store',
  'review-task',
  'external-web',
  'face-recognition-local',
  'manual-health-event',
  'household-member',
  'field-authorization',
] as const

export interface RuntimeStatusLine {
  on: boolean
  label: string
}

export function familyRuntimeLines(capabilities: {
  phase?: string
  available?: string[]
  unavailable?: string[]
} | null): RuntimeStatusLine[] {
  if (!capabilities) {
    return [{ on: false, label: '本地 API · 状态未知' }]
  }
  const available = capabilities.available ?? []
  const unavailable = capabilities.unavailable ?? []
  const lines: RuntimeStatusLine[] = [
    {
      on: true,
      label: `本地 API · 已连接（阶段 ${capabilities.phase ?? '未知'}）`,
    },
  ]
  const seen = new Set<string>()
  for (const key of PREFERRED_ON) {
    if (!available.includes(key) || seen.has(key)) continue
    seen.add(key)
    lines.push({ on: true, label: CAPABILITY_LABELS[key] ?? key })
  }
  if (unavailable.includes('external-web') && !seen.has('external-web')) {
    lines.push({ on: false, label: '受控联网搜索 · 未启用' })
  }
  for (const key of unavailable) {
    if (HIDDEN_UNAVAILABLE.has(key) || key === 'external-web' || seen.has(key)) continue
  }
  return lines
}
