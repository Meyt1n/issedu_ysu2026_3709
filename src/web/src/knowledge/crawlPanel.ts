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

/**
 * 每条 staging 草稿的变更类型：首次抓取（新来源）、内容哈希变化（有更新，
 * 已重置为 draft 待审）或哈希一致（未变更，保留原审核状态）。
 */
export type StagingChangeKind = 'new' | 'changed' | 'unchanged'

export function stagingChangeKind(item: Record<string, unknown>): StagingChangeKind {
  if (item.first_fetch) return 'new'
  return item.unchanged ? 'unchanged' : 'changed'
}

export const STAGING_CHANGE_LABELS: Record<StagingChangeKind, string> = {
  new: '新来源',
  changed: '有更新',
  unchanged: '未变更',
}

/**
 * 抓取结果摘要：区分新来源 / 有更新 / 未变更 / 失败。全部未变更时解释这是
 * 内容哈希一致的正常现象，并指向「模拟来源更新」教学路径，避免用户误以为
 * 抓取坏了或“永远是同一批”。
 */
export function crawlRunSummary(report: Record<string, unknown>): string {
  const fetched = Number(report.fetched ?? 0)
  const changed = Number(report.changed ?? 0)
  const unchanged = Number(report.unchanged ?? 0)
  const newSources = Number(report.new_sources ?? 0)
  const updated = Math.max(0, changed - newSources)
  const errors = Array.isArray(report.errors) ? report.errors.length : 0
  let text = `抓取完成：共 ${fetched} 条 · 新来源 ${newSources} · 有更新 ${updated} · 未变更 ${unchanged}`
  if (errors > 0) text += ` · 失败 ${errors}`
  text += '（不会自动入库）'
  if (fetched > 0 && unchanged === fetched) {
    text +=
      '。全部「未变更」表示来源内容哈希与上次一致，属正常现象；' +
      '可用「模拟来源更新（教学演示）」体验变更检测与重新审核。'
  } else if (newSources > 0 || updated > 0) {
    text += '。新来源与有更新的草稿已重置为 draft，请在下方点「查看」核对正文后重新审核。'
  }
  return text
}

/** 「模拟来源更新（教学演示）」的结果摘要。 */
export function simulateUpdateSummary(report: Record<string, unknown>): string {
  if (report.reset) {
    const cleared = Array.isArray(report.cleared) ? report.cleared.length : 0
    return (
      `已清除 ${cleared} 个教学演示 overlay；` +
      '下次抓取将回到仓库夹具原文（同样会显示「有更新」并重置为 draft）。'
    )
  }
  const bumped = Array.isArray(report.bumped) ? report.bumped.length : 0
  return (
    `已为 ${bumped} 个本地夹具来源叠加清晰标注的教学演示更新（不出网、不改仓库文件）。` +
    '现在点「全量抓取」或「到期刷新」，即可看到「有更新」草稿并重新审核；仍不会自动入库。'
  )
}
