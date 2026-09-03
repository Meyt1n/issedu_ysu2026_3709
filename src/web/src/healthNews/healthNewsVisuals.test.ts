import { describe, expect, it } from 'vitest'

import type { HealthNewsItem } from '../api/types'
import { healthNewsVisualFor } from './healthNewsVisuals'

function item(id: string): HealthNewsItem {
  return {
    id,
    kind: 'seasonal_tip',
    title: '示例卡片',
    summary: '示例摘要',
    tag: '季节提醒',
    chat_prompt: '请问一般有哪些居家照护提醒？',
    source: 'seasonal_calendar',
  }
}

describe('healthNewsVisualFor', () => {
  it('gives each local autumn card its own full-bleed visual', () => {
    const ids = [
      'autumn-transition-dry',
      'autumn-flu-like-caution',
      'autumn-dry-air',
      'autumn-window-airing',
      'autumn-gentle-walk',
      'autumn-family-checkin',
    ]
    const visuals = ids.map((id) => healthNewsVisualFor(item(id)))

    expect(visuals.every(Boolean)).toBe(true)
    expect(new Set(visuals).size).toBe(ids.length)
  })

  it('does not apply any visual to an unknown non-news item', () => {
    expect(healthNewsVisualFor(item('unknown-article'))).toBeNull()
  })

  it('gives remote cards bright editorial art without reusing one slot', () => {
    const remote = {
      ...item('remote-article'),
      kind: 'remote' as const,
      source: 'remote_whitelist' as const,
    }
    const visuals = [0, 1, 2, 3, 4, 5].map((position) =>
      healthNewsVisualFor(remote, position),
    )

    expect(visuals.every(Boolean)).toBe(true)
    expect(new Set(visuals).size).toBe(6)
  })
})
