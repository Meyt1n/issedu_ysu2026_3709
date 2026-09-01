import { describe, expect, it } from 'vitest'

import { familyRuntimeLines } from './runtimeStatus'

describe('familyRuntimeLines', () => {
  it('prefers real local capabilities and hides never-on cloud/formal-set flags', () => {
    const lines = familyRuntimeLines({
      phase: 'P0-foundation',
      available: ['llm', 'local-assistant', 'vision-task', 'manual-health-event'],
      unavailable: ['llm-cloud', 'external-web', 'hct201-formal-drug-set'],
    })
    const labels = lines.map(line => line.label)
    expect(labels[0]).toContain('本地 API')
    expect(labels).toContain('本地大模型')
    expect(labels).toContain('本地助手')
    expect(labels).toContain('受控联网搜索 · 未启用')
    expect(labels.join(' ')).not.toContain('llm-cloud')
    expect(labels.join(' ')).not.toContain('hct201-formal-drug-set')
  })

  it('shows web search as on when the deployment actually enabled it', () => {
    const lines = familyRuntimeLines({
      phase: 'P0-foundation',
      available: ['external-web', 'llm'],
      unavailable: ['llm-cloud'],
    })
    expect(lines.some(line => line.on && line.label === '受控联网搜索')).toBe(true)
    expect(lines.some(line => line.label.includes('未启用'))).toBe(false)
  })
})
