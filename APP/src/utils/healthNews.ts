import type { HealthNewsItem, HealthNewsResponse } from '@/api/types'

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

const DISCLAIMER =
  '公开资讯与季节提醒仅供教学演示，不是疫情通报或诊断依据。具体不适请咨询医生或药师。'

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
    intro: '目标站点未进入白名单，已降级为本地季节提醒。',
  },
  rate_limited: {
    label: '请求限速',
    tone: 'warn',
    intro: '抓取过于频繁，已限速并降级展示。',
  },
  timeout: {
    label: '抓取超时',
    tone: 'warn',
    intro: '权威站点响应超时，已降级为本地季节提醒。',
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
  const hasRemote = (news?.items ?? []).some(item => item.source === 'remote_whitelist')
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
  else if (item.source === 'remote_whitelist') parts.push('白名单公开来源')
  const published = formatWhen(item.published_at)
  if (published) parts.push(`发布 ${published}`)
  const fetched = formatWhen(item.fetched_at)
  if (fetched && item.source === 'remote_whitelist') parts.push(`抓取 ${fetched}`)
  return parts.join(' · ')
}

/** 资讯跳转助手时只生成可编辑草稿，标题与来源始终位于前缀位置。 */
export function assistantPromptForItem(item: HealthNewsItem): string {
  const source = item.source_name
    ?? (item.source === 'remote_whitelist' ? '白名单公开来源' : '本地季节日历')
  return `资讯标题：${item.title}；来源：${source}。${item.chat_prompt}`.slice(0, 240)
}

type Season = 'spring' | 'summer' | 'autumn' | 'winter'

function seasonForMonth(month: number): Season {
  if (month >= 3 && month <= 5) return 'spring'
  if (month >= 6 && month <= 8) return 'summer'
  if (month >= 9 && month <= 11) return 'autumn'
  return 'winter'
}

const SEASONAL_CATALOG: Record<Season, Array<Omit<HealthNewsItem, 'source_name' | 'published_at' | 'fetched_at'>>> = {
  spring: [
    {
      id: 'app-spring-temperature',
      kind: 'seasonal_tip',
      title: '换季温差大，留意着凉与鼻塞咳嗽',
      summary: '早晚凉、白天暖时可先关注衣物增减、通风与休息；想了解一般资料可带着问题询问本地助手。',
      tag: '换季照护',
      chat_prompt: '换季容易着凉，感冒样不适一般可以了解哪些常用药资料？',
      source: 'seasonal_calendar',
    },
    {
      id: 'app-spring-respiratory',
      kind: 'seasonal_tip',
      title: '春季呼吸道不适更常见，先记录再核对资料',
      summary: '鼻塞、咽痒等不适持续时，记录出现时间并向医生或药师咨询，不自行判断具体病因。',
      tag: '季节提醒',
      chat_prompt: '最近换季，呼吸道不适要注意什么？有哪些一般性居家照护提醒？',
      source: 'seasonal_calendar',
    },
  ],
  summer: [
    {
      id: 'app-summer-temperature',
      kind: 'seasonal_tip',
      title: '室内外温差大，外出回家先适应温度',
      summary: '夏季进出空调房时可放慢活动节奏、适量补水并留意身体感受，异常不适及时求助。',
      tag: '夏日照护',
      chat_prompt: '夏季进出空调房有哪些一般性居家照护提醒？',
      source: 'seasonal_calendar',
    },
    {
      id: 'app-summer-heat',
      kind: 'seasonal_tip',
      title: '高温时段减少长时间户外停留',
      summary: '可把外出安排在较凉时段，保持通风和饮水；如出现明显不适，请联系家人或专业人员。',
      tag: '高温提醒',
      chat_prompt: '高温天气里，家人日常照护可以先注意哪些事项？',
      source: 'seasonal_calendar',
    },
  ],
  autumn: [
    {
      id: 'app-autumn-dryness',
      kind: 'seasonal_tip',
      title: '秋季干燥，留意饮水和室内湿度',
      summary: '天气转凉后保持规律作息、适量饮水和通风；鼻咽不适持续时及时咨询专业人员。',
      tag: '秋季照护',
      chat_prompt: '秋季干燥时有哪些不涉及诊断的日常照护资料可以了解？',
      source: 'seasonal_calendar',
    },
    {
      id: 'app-autumn-temperature',
      kind: 'seasonal_tip',
      title: '早晚转凉，外出前查看衣物和活动安排',
      summary: '早晚温度变化时可提前准备合适衣物，家人一起确认当天安排，不把季节提示当作医疗结论。',
      tag: '温差提醒',
      chat_prompt: '秋季早晚温差大，家庭日常安排可以注意什么？',
      source: 'seasonal_calendar',
    },
  ],
  winter: [
    {
      id: 'app-winter-ventilation',
      kind: 'seasonal_tip',
      title: '冬季室内取暖也要定时通风',
      summary: '保持室内空气流通并关注温度变化；家人持续不适时记录情况，联系医生或药师核对。',
      tag: '冬季照护',
      chat_prompt: '冬季室内照护有哪些安全、通用的生活提醒？',
      source: 'seasonal_calendar',
    },
    {
      id: 'app-winter-outdoor',
      kind: 'seasonal_tip',
      title: '寒冷天气外出前先确认路线和保暖',
      summary: '外出前和家人确认路线、衣物与返程安排，遇到明显不适请及时联系专业人员。',
      tag: '出行提醒',
      chat_prompt: '寒冷天气里，老人外出前可以做哪些一般性准备？',
      source: 'seasonal_calendar',
    },
  ],
}

/** 演示模式的虚构季节资讯；不访问网络，也不写入本机持久化存储。 */
export function buildLocalHealthNews(when: Date = new Date()): HealthNewsResponse {
  const season = seasonForMonth(when.getMonth() + 1)
  const generatedAt = when.toISOString()
  return {
    status: 'local_only',
    cache_status: 'none',
    season,
    generated_at: generatedAt,
    fetched_at: null,
    disclaimer: DISCLAIMER,
    degraded_reason: null,
    sources_attempted: [],
    items: SEASONAL_CATALOG[season].map(item => ({
      ...item,
      source_name: '本地季节日历（演示）',
      published_at: null,
      fetched_at: null,
    })),
  }
}
