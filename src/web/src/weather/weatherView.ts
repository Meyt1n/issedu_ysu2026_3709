import type { WeatherResponse } from '../api/types'

export interface WeatherPresentation {
  available: boolean
  stale: boolean
  statusLabel: string
  statusTone: 'sage' | 'gold' | 'plain'
  scopeLabel: string
  sourceLabel: string
  detail: string
}

const DEGRADED_REASONS: Record<string, string> = {
  timeout: '天气服务响应超时，正在显示最后一次有效缓存。',
  rate_limited: '天气服务请求较频繁，正在显示最后一次有效缓存。',
  provider_unavailable: '天气服务暂时不可达，正在显示最后一次有效缓存。',
  error: '天气服务暂时异常，正在显示最后一次有效缓存。',
}

const CALM_WEATHER_MESSAGES = [
  '阳光正好，给今天留一点从容。',
  '风把节奏吹松一些，稳稳向前。',
  '云朵替天空留了空白，也给自己留点呼吸。',
  '今天也辛苦了，按自己的步子慢慢来。',
  '把平常的一天过好，就是很棒的坚持。',
  '轻装出发，给自己一个小小的肯定。',
  '你已经做得很好，今天继续保持好心情。',
  '不赶路，照顾好当下的每一个小片刻。',
  '今天的空气很安静，适合把心情放松一点。',
  '日子会一格一格变好，今天也算一格。',
  '给自己一个温柔的开始，剩下的慢慢来。',
  '平稳就是今天的好消息，继续保持自己的节奏。',
] as const

const CALM_WEATHER_BADGES = [
  '舒展一下',
  '稳稳向前',
  '留点呼吸',
  '慢慢来',
  '很棒的坚持',
  '轻装出发',
  '好心情',
  '照顾当下',
  '放松一点',
  '一格一格好起来',
  '温柔开始',
  '保持节奏',
] as const

function localDayIndex(date: Date): number {
  const start = new Date(date.getFullYear(), 0, 1)
  const current = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  return Math.floor((current.getTime() - start.getTime()) / 86_400_000)
}

export function calmWeatherMessage(date: Date = new Date()): string {
  return CALM_WEATHER_MESSAGES[localDayIndex(date) % CALM_WEATHER_MESSAGES.length]
}

export function calmWeatherBadge(date: Date = new Date()): string {
  return CALM_WEATHER_BADGES[localDayIndex(date) % CALM_WEATHER_BADGES.length]
}

function formatSourceTime(value?: string | null): string {
  if (!value) return '来源时间待提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '来源时间无效'
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `来源时间 ${values.month}月${values.day}日 ${values.hour}:${values.minute}`
}

export function presentWeather(weather: WeatherResponse | null): WeatherPresentation {
  const scopeLabel =
    weather?.location_scope === 'district'
      ? '区县级范围'
      : weather?.location_scope === 'city'
        ? '城市级范围'
        : '粗粒度位置未配置'
  const sourceLabel = formatSourceTime(weather?.source_observed_at ?? weather?.fetched_at)

  if (!weather) {
    return {
      available: false,
      stale: false,
      statusLabel: '天气暂不可用',
      statusTone: 'plain',
      scopeLabel,
      sourceLabel,
      detail: '尚未取得环境数据，家庭事实、规则和任务不受影响。',
    }
  }

  if (weather.status === 'ok') {
    return {
      available: true,
      stale: false,
      statusLabel: weather.cache_status === 'fresh' ? '缓存仍有效' : '天气已更新',
      statusTone: 'sage',
      scopeLabel,
      sourceLabel,
      detail: '仅使用家庭选择的粗粒度行政区划代码获取公开天气。',
    }
  }

  if (weather.status === 'stale') {
    return {
      available: true,
      stale: true,
      statusLabel: '缓存数据 · 已降级',
      statusTone: 'gold',
      scopeLabel,
      sourceLabel,
      detail:
        DEGRADED_REASONS[weather.degraded_reason ?? ''] ??
        '天气服务暂不可用，正在显示最后一次有效缓存。',
    }
  }

  if (weather.status === 'disabled') {
    return {
      available: false,
      stale: false,
      statusLabel: '天气出口未启用',
      statusTone: 'plain',
      scopeLabel,
      sourceLabel,
      detail: '网络出口保持关闭；启用前不会发送任何位置或健康信息。',
    }
  }

  if (weather.status === 'location_required' || weather.status === 'unconfigured') {
    return {
      available: false,
      stale: false,
      statusLabel: '等待安全配置',
      statusTone: 'plain',
      scopeLabel,
      sourceLabel,
      detail: '管理员需配置获批的位置代码、天气域名和缓存策略，家庭核心功能仍可使用。',
    }
  }

  return {
    available: false,
    stale: false,
    statusLabel: '天气暂不可用',
    statusTone: 'plain',
    scopeLabel,
    sourceLabel,
    detail: '没有可验证的实时或缓存数据，家庭事实、规则和任务不受影响。',
  }
}
