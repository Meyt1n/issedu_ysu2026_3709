import type { AssistantAgentCatalog } from '../api/types'

/**
 * UI-facing availability state for the HCT-430 controlled web-search toggle.
 * Derived from the agent catalog so the assistant page can explain exactly why
 * search is unavailable and how a deployment operator can enable it.
 */
export interface WebSearchAvailability {
  /** null = catalog unavailable (API unreachable); do not disable the toggle. */
  available: boolean | null
  /** True when the deployment serves offline teaching fixtures (no egress). */
  fixture: boolean
  reason: string | null
  hint: string | null
}

export function webSearchAvailabilityFromCatalog(
  catalog: AssistantAgentCatalog,
): WebSearchAvailability {
  return {
    available: catalog.web_search_ready ?? catalog.web_search_enabled,
    fixture: catalog.web_search_offline_fixture === true,
    reason: catalog.web_search_unavailable_reason ?? null,
    hint: catalog.web_search_enable_hint ?? null,
  }
}

export function unavailableWebSearchAvailability(): WebSearchAvailability {
  return { available: null, fixture: false, reason: null, hint: null }
}

/** Copy for the disabled checkbox, keyed on the machine-readable reason. */
export function webSearchDisabledLabel(state: WebSearchAvailability): string {
  if (state.reason === 'EGRESS_BLOCKED') {
    return '联网参考已在部署开启，但搜索地址未通过出口白名单校验，暂不可用。'
  }
  return '联网参考未在当前部署启用，全部分析在本机完成。'
}

/** Detail line for the skipped web-search stage in the workflow panel. */
export function webSearchSkipDetail(state: WebSearchAvailability): string {
  if (state.available === false) {
    return state.reason === 'EGRESS_BLOCKED'
      ? '搜索地址未通过出口白名单校验'
      : '当前部署未启用联网参考'
  }
  return '本次请求未开启联网搜索'
}
