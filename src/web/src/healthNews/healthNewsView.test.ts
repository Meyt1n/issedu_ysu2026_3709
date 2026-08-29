import { describe, expect, it } from 'vitest'

import type { HealthNewsResponse } from '../api/types'
import { itemSourceLine, presentHealthNews } from './healthNewsView'

const base: HealthNewsResponse = {
  status: 'local_only',
  cache_status: 'none',
  season: 'summer',
  generated_at: '2026-08-25T03:00:00+08:00',
  disclaimer: '教学演示',
  items: [
    {
      id: 'summer-ac-chill',
      kind: 'seasonal_tip',
      title: '空调房温差',
      summary: '注意温差',
      tag: '夏季照护',
      chat_prompt: '夏天吹空调后有点鼻塞？',
      source: 'seasonal_calendar',
      source_name: '本地季节日历',
    },
  ],
}

describe('presentHealthNews', () => {
  it('labels local-only seasonal mode', () => {
    const view = presentHealthNews(base)
    expect(view.statusLabel).toContain('本地')
    expect(view.title).toContain('季节')
  })

  it('does not imply online news when egress is blocked', () => {
    const view = presentHealthNews({
      ...base,
      status: 'egress_blocked',
      degraded_reason: 'allowlist_rejected',
      fetched_at: '2026-08-25T04:00:00+00:00',
    })

    expect(view.statusLabel).toBe('出口已拦截')
    expect(view.title).toContain('季节')
    expect(view.intro).toContain('未联网')
    expect(view.intro).toContain('本地季节提醒')
    expect(view.showRemoteMeta).toBe(false)
    expect(view.fetchedLabel).toContain('抓取于')
    expect(view.degradedLabel).toContain('allowlist_rejected')
  })

  it('shows remote fetch meta for whitelist cards', () => {
    const view = presentHealthNews({
      ...base,
      status: 'ok',
      cache_status: 'fresh',
      fetched_at: '2026-08-25T04:00:00+00:00',
      items: [
        {
          id: 'remote-1',
          kind: 'remote',
          title: 'Heat guidance',
          summary: 'Stay cool',
          tag: '权威资讯',
          chat_prompt: '请结合本地知识库说明一般性注意点',
          source: 'remote_whitelist',
          source_name: '世界卫生组织',
          source_url: 'https://www.who.int/news/item/01-heat',
          fetched_at: '2026-08-25T04:00:00+00:00',
        },
      ],
    })
    expect(view.showRemoteMeta).toBe(true)
    expect(view.fetchedLabel).toContain('抓取于')
    expect(view.title).toContain('资讯')
  })

  it('formats item source line', () => {
    const line = itemSourceLine({
      id: 'remote-1',
      kind: 'remote',
      title: 'Heat guidance',
      summary: 'Stay cool',
      tag: '权威资讯',
      chat_prompt: '问助手',
      source: 'remote_whitelist',
      source_name: '世界卫生组织',
      source_url: 'https://www.who.int/news/item/01-heat',
      published_at: '2026-08-25T10:00:00+00:00',
      fetched_at: '2026-08-25T11:00:00+00:00',
    })
    expect(line).toContain('世界卫生组织')
    expect(line).toContain('抓取')
  })
})
