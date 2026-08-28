import { describe, expect, it } from 'vitest'

import type { HealthNewsResponse } from '@/api/types'
import { assistantPromptForItem, buildLocalHealthNews, itemSourceLine, presentHealthNews } from './healthNews'

describe('移动端健康资讯展示映射（MOB-159）', () => {
  it('演示模式返回明确标注的本地季节资讯', () => {
    const news = buildLocalHealthNews(new Date('2026-08-28T04:00:00.000Z'))

    expect(news).toMatchObject({ status: 'local_only', cache_status: 'none', season: 'summer' })
    expect(news.items).toHaveLength(2)
    expect(news.items.every(item => item.source === 'seasonal_calendar')).toBe(true)
    expect(news.items.every(item => item.source_name?.includes('演示'))).toBe(true)
    const cardCopy = news.items.map(item => `${item.title} ${item.summary} ${item.chat_prompt}`).join(' ')
    expect(cardCopy).not.toMatch(/停药|换药|剂量|诊断|处方|购药|问诊/)
    const prompt = assistantPromptForItem(news.items[0]!)
    expect(prompt).toContain(news.items[0]!.title)
    expect(prompt).toContain(news.items[0]!.source_name!)
    expect(prompt.length).toBeLessThanOrEqual(240)
  })

  it('白名单资讯展示抓取时间和来源，缓存态不会伪装成实时', () => {
    const news: HealthNewsResponse = {
      status: 'stale',
      cache_status: 'stale',
      season: 'summer',
      generated_at: '2026-08-28T04:00:00.000Z',
      fetched_at: '2026-08-27T04:00:00.000Z',
      disclaimer: '仅供教学演示',
      degraded_reason: 'timeout',
      items: [{
        id: 'remote-1',
        kind: 'remote',
        title: '公开季节照护资料',
        summary: '来自白名单站点的公开摘要。',
        tag: '权威资讯',
        chat_prompt: '这条公开资料可以怎样理解？',
        source: 'remote_whitelist',
        source_name: '白名单公开来源',
        source_url: 'https://example.com/news',
        published_at: '2026-08-26T04:00:00.000Z',
        fetched_at: '2026-08-27T04:00:00.000Z',
      }],
    }

    const view = presentHealthNews(news)
    expect(view).toMatchObject({ statusLabel: '缓存资讯', statusTone: 'warn', showRemoteMeta: true })
    expect(view.fetchedLabel).toContain('抓取于')
    expect(view.degradedLabel).toContain('timeout')
    expect(itemSourceLine(news.items[0]!)).toContain('白名单公开来源')
    expect(itemSourceLine(news.items[0]!)).toContain('发布')
    expect(itemSourceLine(news.items[0]!)).toContain('抓取')
  })

  it('服务端不可用且没有正文时使用清晰的降级状态', () => {
    const view = presentHealthNews({
      status: 'provider_unavailable',
      season: 'winter',
      generated_at: '2026-08-28T04:00:00.000Z',
      disclaimer: '仅供教学演示',
      items: [],
    })

    expect(view.statusLabel).toBe('来源不可用')
    expect(view.statusTone).toBe('warn')
    expect(view.intro).toContain('降级')
  })
})
