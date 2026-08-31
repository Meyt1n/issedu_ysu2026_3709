import { describe, expect, it } from 'vitest'

import type { AssistantExternalSource } from '@/api/types'
import {
  collectExternalDomains,
  MAX_EXTERNAL_DOMAINS,
  networkSearchDisabledReason,
  networkSearchFailureMessage,
  resolveNetworkSearchForTurn,
} from './networkSearch'

function source(overrides: Partial<AssistantExternalSource> = {}): AssistantExternalSource {
  return { title: '公开科普页', domain: 'example.org', ...overrides }
}

describe('联网来源域名展示', () => {
  it('去重并保留服务端返回的域名顺序', () => {
    const domains = collectExternalDomains([
      source({ domain: 'a.example' }),
      source({ domain: 'b.example' }),
      source({ domain: 'a.example' }),
    ])
    expect(domains).toEqual(['a.example', 'b.example'])
  })

  it('丢弃缺失或空白域名，不用 URL 兜底推断', () => {
    const domains = collectExternalDomains([
      source({ domain: '   ' }),
      source({ domain: undefined }),
      { title: '只有链接', url: 'https://c.example/page' } as AssistantExternalSource,
      source({ domain: 'c.example' }),
    ])
    expect(domains).toEqual(['c.example'])
  })

  it('限制展示数量并容忍空输入', () => {
    const many = Array.from({ length: MAX_EXTERNAL_DOMAINS + 4 }, (_, i) =>
      source({ domain: `d${i}.example` }),
    )
    expect(collectExternalDomains(many)).toHaveLength(MAX_EXTERNAL_DOMAINS)
    expect(collectExternalDomains(null)).toEqual([])
    expect(collectExternalDomains(undefined)).toEqual([])
  })
})

describe('联网开关的 fail-closed 判定', () => {
  const available = { liveMode: true, capabilityProbed: true, externalWebAvailable: true }

  it('服务端声明 external-web 时才判定可用', () => {
    expect(networkSearchDisabledReason(available)).toBe('')
  })

  it('演示模式下不联网', () => {
    expect(networkSearchDisabledReason({ ...available, liveMode: false })).toContain('演示模式')
  })

  it('能力探测未完成时按不可用处理，而不是乐观放行', () => {
    const reason = networkSearchDisabledReason({ ...available, capabilityProbed: false })
    expect(reason).toContain('能力探测尚未完成')
  })

  it('未声明 external-web 时说明当前部署未开放，不谎称联网', () => {
    const reason = networkSearchDisabledReason({ ...available, externalWebAvailable: false })
    expect(reason).toBe('当前部署未开放联网搜索。')
  })
})

describe('单轮是否出网的决策', () => {
  it('能力与用户开关同时成立才出网', () => {
    expect(resolveNetworkSearchForTurn({ available: true, userEnabled: true })).toBe(true)
    expect(resolveNetworkSearchForTurn({ available: true, userEnabled: false })).toBe(false)
  })

  it('缺少服务端能力时，开关残留为开也不出网', () => {
    expect(resolveNetworkSearchForTurn({ available: false, userEnabled: true })).toBe(false)
  })

  it('「仅用本地知识重试」这一轮强制不出网', () => {
    expect(
      resolveNetworkSearchForTurn({ localOnly: true, available: true, userEnabled: true }),
    ).toBe(false)
  })
})

describe('联网失败后的可恢复提示', () => {
  it('服务端以降级 trace 返回限流时仍提供本地重试语义', () => {
    expect(networkSearchFailureMessage([
      { agent_id: 'web_search', status: 'degraded', reason_code: 'RATE_LIMITED' },
    ])).toContain('仅用本地知识重试')
  })

  it('搜索失败（含超时/上游失败）映射为可恢复提示', () => {
    expect(networkSearchFailureMessage([
      { agent_id: 'web_search', status: 'degraded', reason_code: 'SEARCH_FAILED' },
    ])).toContain('超时或上游失败')
  })

  it('没有降级的联网节点时不误报失败', () => {
    expect(networkSearchFailureMessage([
      { agent_id: 'web_search', status: 'completed', reason_code: 'RATE_LIMITED' },
    ])).toBeNull()
  })
})
