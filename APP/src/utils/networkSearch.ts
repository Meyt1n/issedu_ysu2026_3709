import type { AssistantAgentTrace, AssistantExternalSource } from '@/api/types'

/** 展示上限只影响移动端排版，不改变服务端实际使用的来源数量。 */
export const MAX_EXTERNAL_DOMAINS = 8

/**
 * 只从服务端返回的外部来源里取域名，去重并限量。
 * 不展示完整 URL，也不在本地解析或补全域名，避免呈现未经服务端核验的地址。
 */
export function collectExternalDomains(
  sources?: AssistantExternalSource[] | null,
): string[] {
  const domains: string[] = []
  const seen = new Set<string>()
  for (const source of sources ?? []) {
    const domain = typeof source?.domain === 'string' ? source.domain.trim() : ''
    if (!domain || seen.has(domain)) continue
    seen.add(domain)
    domains.push(domain.slice(0, 120))
    if (domains.length >= MAX_EXTERNAL_DOMAINS) break
  }
  return domains
}

/**
 * 联网搜索不可用的原因；返回空串表示可用。
 * fail-closed：能力探测未完成与未声明 `external-web` 都视为不可用，
 * 绝不静默降级成本地检索却对外声称联网。
 */
export function networkSearchDisabledReason(input: {
  liveMode: boolean
  capabilityProbed: boolean
  externalWebAvailable: boolean
}): string {
  if (!input.liveMode) return '演示模式不联网，也不调用家庭服务器。'
  if (!input.capabilityProbed) {
    return '能力探测尚未完成；请先到「我的」测试连接，在此之前联网搜索按不可用处理。'
  }
  if (!input.externalWebAvailable) return '当前部署未开放联网搜索。'
  return ''
}

/**
 * 决定这一轮是否请求出网。三个条件必须同时成立：
 * 本轮未被强制本地、服务端声明了能力、用户显式打开了开关。
 */
export function resolveNetworkSearchForTurn(input: {
  localOnly?: boolean
  available: boolean
  userEnabled: boolean
}): boolean {
  if (input.localOnly === true) return false
  return input.available && input.userEnabled
}

/**
 * 将服务端联网节点的降级原因转成可执行的移动端提示。
 * 联网失败时服务端仍会返回本地回答，因此不能只依赖 HTTP 异常来提供重试入口。
 */
export function networkSearchFailureMessage(
  traces?: AssistantAgentTrace[] | null,
): string | null {
  const trace = (traces ?? []).find(
    item => item.agent_id === 'web_search' && item.status === 'degraded',
  )
  if (!trace) return null

  switch (trace.reason_code) {
    case 'RATE_LIMITED':
      return '联网参考暂时限流，已生成本地回答；可以稍后重试，或仅用本地知识重试。'
    case 'DEPLOYMENT_DISABLED':
      return '当前部署未开放联网参考，已生成本地回答；可以仅用本地知识重试。'
    case 'EGRESS_BLOCKED':
      return '联网参考未通过出口安全校验，已生成本地回答；可以仅用本地知识重试。'
    case 'SEARCH_FAILED':
      return '联网参考暂时不可用（可能是超时或上游失败），已生成本地回答；可以稍后重试，或仅用本地知识重试。'
    default:
      return '联网参考未成功，已生成本地回答；可以稍后重试，或仅用本地知识重试。'
  }
}
