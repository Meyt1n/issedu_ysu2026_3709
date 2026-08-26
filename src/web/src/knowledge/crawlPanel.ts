import { ApiClientError } from '../api/client'

/**
 * Access state for the controlled knowledge-crawl panel.  A 403 from the crawl
 * endpoints means the actor is not a knowledge steward and must see explicit
 * guidance instead of a silent empty list.  Other failures are classified so
 * the panel can show the real cause instead of a blanket "API 不可用"：
 * `network`（连不上 API）、`timeout`（API 挂起/重启中）、`config-missing`
 * （部署缺少 allowlist/夹具）与其余 `error`。
 */
export type CrawlPanelAccess =
  | 'ok'
  | 'forbidden'
  | 'network'
  | 'timeout'
  | 'config-missing'
  | 'error'

export function crawlAccessFromError(cause: unknown): CrawlPanelAccess {
  if (!(cause instanceof ApiClientError)) return 'error'
  if (cause.status === 403) return 'forbidden'
  if (cause.code === 'DEPENDENCY_UNAVAILABLE') return 'network'
  if (cause.code === 'REQUEST_TIMEOUT') return 'timeout'
  if (cause.message === 'KNOWLEDGE_CRAWL_CONFIG_MISSING') return 'config-missing'
  return 'error'
}

export const CRAWL_FORBIDDEN_GUIDANCE =
  '知识爬虫与草稿审核仅对知识管理员开放。演示环境请把身份切换为 demo-parent、knowledge-steward ' +
  '或任意 demo- 开头的演示账号；正式部署由负责人把账号加入 .env 的 KNOWLEDGE_ADMIN_ACTORS 后重启 API。'

/** Staging drafts the one-click teaching loop may approve. */
export function pendingTeachingDrafts(
  items: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  return items.filter((item) => item.status === 'draft' || item.status === 'reviewed')
}

export function teachingLoopSummary(
  fetched: number,
  approved: number,
  promoted: number,
): string {
  return (
    `教学闭环完成：抓取 ${fetched} 条 → 批准 ${approved} 条 → 晋升 ${promoted} 篇。` +
    '下一步在终端执行 dry-run 预检查（仍不会自动入库）。'
  )
}
