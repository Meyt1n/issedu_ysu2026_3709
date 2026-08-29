import { describe, expect, it } from 'vitest'

import type { HealthNewsResponse } from '@/api/types'
import { assistantPromptForItem, buildLocalHealthNews, itemSourceLine, presentHealthNews, presentHealthNewsFreshness, refreshOutcomeMessage } from './healthNews'

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
    // MOB-165：cache_status 为 stale 时状态标签改为「缓存已过期」，比原来的「缓存资讯」更直白。
    expect(view).toMatchObject({ statusLabel: '缓存已过期', statusTone: 'warn', showRemoteMeta: true })
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

describe('健康资讯缓存新鲜度与刷新反馈（MOB-165）', () => {
  function newsWith(patch: Partial<HealthNewsResponse>): HealthNewsResponse {
    return {
      status: 'ok',
      cache_status: 'fresh',
      season: 'summer',
      generated_at: '2026-08-29T02:00:00.000Z',
      fetched_at: '2026-08-29T01:30:00.000Z',
      disclaimer: '仅供教学演示',
      items: [],
      ...patch,
    }
  }

  it('过期缓存要显著提示并突出刷新入口', () => {
    const freshness = presentHealthNewsFreshness(newsWith({ cache_status: 'stale' }))

    expect(freshness).toMatchObject({ fromCache: true, expired: true, tone: 'warn', emphasizeRefresh: true })
    expect(freshness.notice).toContain('缓存')
    expect(freshness.notice).toContain('已超过有效期')
    expect(freshness.notice).toContain('刷新')
    expect(freshness.whenLabel).not.toBe('')
  })

  it('有效期内的缓存也必须写明是缓存并带时间', () => {
    const freshness = presentHealthNewsFreshness(newsWith({ cache_status: 'fresh' }))

    expect(freshness).toMatchObject({ fromCache: true, expired: false, emphasizeRefresh: false })
    expect(freshness.notice).toContain('缓存')
    expect(freshness.notice).toContain('仍在有效期内')
    expect(freshness.notice).toContain(freshness.whenLabel)
  })

  it('服务端没给缓存时间时明说无法判断新鲜度，不出现无标注的旧内容', () => {
    const freshness = presentHealthNewsFreshness(newsWith({ cache_status: 'stale', fetched_at: null }))

    expect(freshness.whenLabel).toBe('')
    expect(freshness.notice).toContain('未返回缓存时间')
    expect(freshness.notice).toContain('无法判断新鲜度')
    expect(freshness.expired).toBe(true)
  })

  it('本轮实时取回时不标成缓存', () => {
    const freshness = presentHealthNewsFreshness(newsWith({ cache_status: 'miss' }))

    expect(freshness).toMatchObject({ fromCache: false, expired: false })
    expect(freshness.notice).toContain('本轮从家庭服务器取得')
    expect(freshness.notice).not.toContain('缓存')
  })

  it('缓存内容的状态标签不使用暗示实时的措辞', () => {
    const cached = presentHealthNews(newsWith({ status: 'ok', cache_status: 'fresh' }))
    expect(cached.statusLabel).toBe('缓存资讯')
    expect(cached.statusLabel).not.toBe('已更新')

    const live = presentHealthNews(newsWith({ status: 'ok', cache_status: 'miss' }))
    expect(live.statusLabel).toBe('已更新')
  })

  it('刷新反馈不谎报成功：仍是缓存就说仍是缓存', () => {
    expect(refreshOutcomeMessage(newsWith({ cache_status: 'miss' }))).toContain('新取回')

    const staleMessage = refreshOutcomeMessage(newsWith({ cache_status: 'stale' }))
    expect(staleMessage).toContain('仍只能提供过期缓存')
    expect(staleMessage).not.toContain('最新')

    const freshMessage = refreshOutcomeMessage(newsWith({ cache_status: 'fresh' }))
    expect(freshMessage).toContain('仍是有效期内的缓存')

    expect(refreshOutcomeMessage(null)).toContain('保留原有资讯')
  })

  it('没有内容时新鲜度为空，不编造时间', () => {
    expect(presentHealthNewsFreshness(null)).toMatchObject({
      fromCache: false,
      expired: false,
      whenLabel: '',
      notice: '',
    })
  })
})
