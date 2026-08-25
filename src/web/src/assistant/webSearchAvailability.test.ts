import { describe, expect, it } from 'vitest'

import type { AssistantAgentCatalog } from '../api/types'
import {
  unavailableWebSearchAvailability,
  webSearchAvailabilityFromCatalog,
  webSearchDisabledLabel,
  webSearchModeBadge,
  webSearchSkipDetail,
} from './webSearchAvailability'

function catalog(overrides: Partial<AssistantAgentCatalog>): AssistantAgentCatalog {
  return {
    mode: 'multi_agent',
    all_agents_local: true,
    ollama_local_only: true,
    web_search_enabled: false,
    web_search_requires_request_opt_in: true,
    agents: [],
    ...overrides,
  }
}

describe('webSearchAvailabilityFromCatalog', () => {
  it('marks a disabled deployment with the reason and enable hint', () => {
    const state = webSearchAvailabilityFromCatalog(
      catalog({
        web_search_enabled: false,
        web_search_ready: false,
        web_search_unavailable_reason: 'DEPLOYMENT_DISABLED',
        web_search_enable_hint: '在 .env 设置 AGENT_WEB_SEARCH_ENABLED=true 并重启 API。',
      }),
    )
    expect(state.available).toBe(false)
    expect(state.reason).toBe('DEPLOYMENT_DISABLED')
    expect(state.hint).toContain('AGENT_WEB_SEARCH_ENABLED')
    expect(state.fixture).toBe(false)
  })

  it('marks a ready fixture deployment as available and offline', () => {
    const state = webSearchAvailabilityFromCatalog(
      catalog({
        web_search_enabled: true,
        web_search_ready: true,
        web_search_provider: 'fixture',
        web_search_offline_fixture: true,
        web_search_unavailable_reason: 'OPT_IN_REQUIRED',
      }),
    )
    expect(state.available).toBe(true)
    expect(state.fixture).toBe(true)
    expect(state.reason).toBe('OPT_IN_REQUIRED')
  })

  it('falls back to web_search_enabled for older catalogs', () => {
    const state = webSearchAvailabilityFromCatalog(catalog({ web_search_enabled: true }))
    expect(state.available).toBe(true)
  })
})

describe('webSearchDisabledLabel', () => {
  it('explains a deployment switch that is off', () => {
    const state = webSearchAvailabilityFromCatalog(
      catalog({ web_search_unavailable_reason: 'DEPLOYMENT_DISABLED' }),
    )
    expect(webSearchDisabledLabel(state)).toContain('未在当前部署启用')
  })

  it('distinguishes an egress allowlist failure', () => {
    const state = webSearchAvailabilityFromCatalog(
      catalog({
        web_search_enabled: true,
        web_search_ready: false,
        web_search_unavailable_reason: 'EGRESS_BLOCKED',
      }),
    )
    expect(webSearchDisabledLabel(state)).toContain('出口白名单')
  })
})

describe('webSearchSkipDetail', () => {
  it('reports the deployment state when search is unavailable', () => {
    const blocked = webSearchAvailabilityFromCatalog(
      catalog({
        web_search_enabled: true,
        web_search_ready: false,
        web_search_unavailable_reason: 'EGRESS_BLOCKED',
      }),
    )
    expect(webSearchSkipDetail(blocked)).toContain('出口白名单')

    const disabled = webSearchAvailabilityFromCatalog(
      catalog({ web_search_ready: false, web_search_unavailable_reason: 'DEPLOYMENT_DISABLED' }),
    )
    expect(webSearchSkipDetail(disabled)).toContain('未启用联网参考')
  })

  it('reports missing opt-in when the deployment is ready', () => {
    const ready = webSearchAvailabilityFromCatalog(
      catalog({
        web_search_enabled: true,
        web_search_ready: true,
        web_search_unavailable_reason: 'OPT_IN_REQUIRED',
      }),
    )
    expect(webSearchSkipDetail(ready)).toContain('未开启联网搜索')
  })

  it('does not disable the toggle when the catalog is unreachable', () => {
    expect(unavailableWebSearchAvailability().available).toBeNull()
  })
})

describe('webSearchModeBadge', () => {
  it('labels a ready fixture deployment as offline teaching mode', () => {
    const state = webSearchAvailabilityFromCatalog(
      catalog({
        web_search_enabled: true,
        web_search_ready: true,
        web_search_provider: 'fixture',
        web_search_offline_fixture: true,
      }),
    )
    expect(webSearchModeBadge(state)).toBe('教学夹具 · 不出网')
  })

  it('labels a ready real provider as allowlisted real egress', () => {
    const state = webSearchAvailabilityFromCatalog(
      catalog({
        web_search_enabled: true,
        web_search_ready: true,
        web_search_provider: 'duckduckgo_html',
        web_search_offline_fixture: false,
      }),
    )
    expect(webSearchModeBadge(state)).toBe('真实联网 · 白名单出口')
    expect(state.provider).toBe('duckduckgo_html')
  })

  it('shows no badge when search is unavailable or unknown', () => {
    expect(webSearchModeBadge(unavailableWebSearchAvailability())).toBeNull()
    const disabled = webSearchAvailabilityFromCatalog(
      catalog({ web_search_enabled: false, web_search_ready: false }),
    )
    expect(webSearchModeBadge(disabled)).toBeNull()
  })
})
