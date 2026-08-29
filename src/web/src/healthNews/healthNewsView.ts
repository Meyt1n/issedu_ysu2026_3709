import type { HealthNewsItem, HealthNewsResponse } from '../api/types'

export type HealthNewsTone = 'ok' | 'warn' | 'muted'

export interface HealthNewsPresentation {
  title: string
  intro: string
  statusLabel: string
  statusTone: HealthNewsTone
  showRemoteMeta: boolean
  fetchedLabel: string
  degradedLabel: string
}

const STATUS_COPY: Record<string, { label: string; tone: HealthNewsTone; intro: string }> = {
  ok: {
    label: '已更新',
    tone: 'ok',
    intro: '以下包含白名单权威站点公开资讯与本地季节提醒。点一条可带着问题进入本地助手。',
  },
  stale: {
    label: '缓存资讯',
    tone: 'warn',
    intro: '外网暂时不可用，正在展示最近一次成功抓取的缓存，并辅以本地季节提醒。',
  },
  local_only: {
    label: '本地季节',
    tone: 'muted',
    intro: '当前为本地季节照护提醒（未启用外网资讯）。点一条即可带着问题进入本地助手。',
  },
  disabled: {
    label: '已关闭外网',
    tone: 'muted',
    intro: '健康新闻外网抓取已关闭，仅展示本地季节提醒。',
  },
  unconfigured: {
    label: '待配置白名单',
    tone: 'warn',
    intro: '外网资讯未配置域名白名单，已降级为本地季节提醒。',
  },
  egress_blocked: {
    label: '出口已拦截',
    tone: 'warn',
    intro: '当前未联网抓取或显示实时新闻：目标站点未进入白名单，仅展示本地季节提醒。',
  },
  rate_limited: {
    label: '请求限速',
    tone: 'warn',
    intro: '抓取过于频繁，已限速并降级展示。',
  },
  timeout: {
    label: '抓取超时',
    tone: 'warn',
    intro: '权威站点响应超时，已降级为本地季节提醒（不会编造疫情内容）。',
  },
  provider_unavailable: {
    label: '来源不可用',
    tone: 'warn',
    intro: '权威站点暂时不可用，已降级为本地季节提醒。',
  },
  invalid_response: {
    label: '响应无效',
    tone: 'warn',
    intro: '来源响应无法解析，已降级为本地季节提醒。',
  },
  error: {
    label: '暂时不可用',
    tone: 'warn',
    intro: '健康新闻服务异常，已降级为本地季节提醒。',
  },
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function presentHealthNews(news: HealthNewsResponse | null): HealthNewsPresentation {
  const status = news?.status ?? 'local_only'
  const copy = STATUS_COPY[status] ?? STATUS_COPY.error
  const fetchedLabel = formatWhen(news?.fetched_at)
  const hasRemote = (news?.items ?? []).some((item) => item.source === 'remote_whitelist')
  return {
    title: hasRemote ? '近期健康资讯' : '换季与季节照护提醒',
    intro: copy.intro,
    statusLabel: copy.label,
    statusTone: copy.tone,
    showRemoteMeta: Boolean(fetchedLabel) && (hasRemote || status === 'stale' || status === 'ok'),
    fetchedLabel: fetchedLabel ? `抓取于 ${fetchedLabel}` : '',
    degradedLabel: news?.degraded_reason ? `降级原因：${news.degraded_reason}` : '',
  }
}

export function itemSourceLine(item: HealthNewsItem): string {
  const parts: string[] = []
  if (item.source_name) parts.push(item.source_name)
  else if (item.source === 'seasonal_calendar') parts.push('本地季节日历')
  const published = formatWhen(item.published_at ?? undefined)
  if (published) parts.push(`发布 ${published}`)
  const fetched = formatWhen(item.fetched_at ?? undefined)
  if (fetched && item.source === 'remote_whitelist') parts.push(`抓取 ${fetched}`)
  return parts.join(' · ')
}
