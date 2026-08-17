const dayMs = 24 * 60 * 60 * 1000

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function startOfDay(date: Date): number {
  const copy = new Date(date)
  copy.setHours(0, 0, 0, 0)
  return copy.getTime()
}

/** 把 ISO 时间格式化为“今天 08:00 / 明天 19:00 / 8月15日 09:30”。 */
export function formatDateTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '时间未知'
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const diffDays = Math.round((startOfDay(date) - startOfDay(now)) / dayMs)
  if (diffDays === 0) return `今天 ${time}`
  if (diffDays === 1) return `明天 ${time}`
  if (diffDays === -1) return `昨天 ${time}`
  return `${date.getMonth() + 1}月${date.getDate()}日 ${time}`
}

export function formatDay(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '日期未知'
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
}

/** 按名字稳定映射到 1-4 号头像配色（绿/蜜桃/湖青/丁香）。 */
export function avatarHue(text: string): number {
  let sum = 0
  for (const char of text) sum += char.codePointAt(0) ?? 0
  return (sum % 4) + 1
}

export function greetingByHour(hour: number): string {
  if (hour < 5) return '夜深了'
  if (hour < 9) return '早上好'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
}
