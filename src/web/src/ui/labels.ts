import type { HealthEvent } from '../api/types'

export const EVENT_TYPE_LABELS: Record<string, string> = {
  medication_added: '新增药品',
  medication_corrected: '修正药品',
  allergy_added: '新增过敏史',
  allergy_removed: '移除过敏史',
  disease_added: '新增疾病记录',
  disease_resolved: '疾病痊愈',
  plan_created: '创建用药计划',
  plan_updated: '更新用药计划',
  plan_confirmed: '确认服药',
  plan_deferred: '延期服药',
  plan_skipped: '跳过服药',
  plan_missed: '漏服记录',
  care_escalated: '照护升级',
  caregiver_notified: '已通知照护者',
  metric_recorded: '指标观察记录',
  caregiver_assigned: '指定照护者',
  report_added: '新增检查报告',
  note_added: '照护备注',
  COMPENSATION: '补偿更正',
}

export function eventTypeLabel(eventType: string, audience: 'member' | 'admin' = 'admin'): string {
  const label = EVENT_TYPE_LABELS[eventType]
  if (label) return label
  return audience === 'member' ? '一条家庭记录' : eventType
}

export const EVENT_TYPE_TONE: Record<string, string> = {
  medication_added: 'pine',
  medication_corrected: 'gold',
  allergy_added: 'rose',
  allergy_removed: 'sage',
  disease_added: 'rose',
  disease_resolved: 'sage',
  plan_created: 'sky',
  plan_updated: 'sky',
  plan_confirmed: 'pine',
  plan_deferred: 'gold',
  plan_skipped: 'gold',
  plan_missed: 'rose',
  care_escalated: 'rose',
  caregiver_notified: 'sky',
  metric_recorded: 'sky',
  caregiver_assigned: 'sky',
  report_added: 'sky',
  note_added: 'sage',
  COMPENSATION: 'gold',
}

export function eventTone(eventType: string): string {
  return EVENT_TYPE_TONE[eventType] ?? 'sage'
}

export const MEMBER_ROLE_LABELS: Record<string, string> = {
  SELF: '本人',
  DEPENDENT: '被照护成员',
  CAREGIVER: '照护者',
}

export function memberRoleLabel(role: string): string {
  return MEMBER_ROLE_LABELS[role] ?? role
}

export const VISION_STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '处理中',
  succeeded: '处理完成',
  failed: '处理失败',
  cancelled: '已取消',
  timeout: '已超时',
}

export function visionStatusLabel(status: string): string {
  return VISION_STATUS_LABELS[status] ?? status
}

export const REVIEW_STATUS_LABELS: Record<string, string> = {
  PENDING_REVIEW: '待复核',
  CONFIRMED: '已确认',
  CORRECTED: '已修正',
  SKIPPED: '已跳过',
}

export function reviewStatusLabel(status: string): string {
  return REVIEW_STATUS_LABELS[status] ?? status
}

export const FUSION_STATUS_LABELS: Record<string, string> = {
  MATCHED: '候选明确',
  CONFLICT: '证据冲突',
  UNKNOWN: '无法识别',
  REVIEW: '信息不足',
  LOW_QUALITY: '信息不足',
  READY_FOR_FUSION: '待融合',
}

export function fusionStatusLabel(status: string | null): string {
  if (!status) return '未知状态'
  return FUSION_STATUS_LABELS[status] ?? status
}

export const CONFIRMATION_LABELS: Record<string, string> = {
  CONFIRMED: '已确认',
  UNCONFIRMED: '待确认',
}

export function confirmationLabel(status: string): string {
  return CONFIRMATION_LABELS[status] ?? status
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '时间不可用'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间不可用'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '时间不可用'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间不可用'
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return ''
  const timestamp = new Date(value).getTime()
  if (Number.isNaN(timestamp)) return ''
  const diffMs = Date.now() - timestamp
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return formatDate(value)
}

export function greetingByHour(hour: number = new Date().getHours()): string {
  if (hour < 5) return '夜深了'
  if (hour < 9) return '早上好'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  if (hour < 22) return '晚上好'
  return '夜深了'
}

export function summarizeEventPayload(event: HealthEvent): string {
  const payload = event.payload ?? {}
  const parts: string[] = []
  const known: Array<[string, string]> = [
    ['drug', '药品'],
    ['allergy', '过敏原'],
    ['disease', '疾病'],
    ['metric', '指标'],
    ['systolic', '收缩压'],
    ['diastolic', '舒张压'],
    ['value', '数值'],
    ['unit', '单位'],
    ['meal_context', '餐次'],
    ['schedule', '安排'],
    ['dosage', '剂量'],
    ['frequency', '频次'],
    ['reason', '原因'],
    ['note', '备注'],
    ['text', '内容'],
    ['caregiver_id', '照护者'],
    ['recipient_actor_id', '通知对象'],
    ['delay_hours', '延期小时'],
  ]
  for (const [key, label] of known) {
    const value = payload[key]
    if (value !== undefined && value !== null && value !== '') {
      parts.push(`${label}：${String(value)}`)
    }
  }
  if (parts.length === 0) {
    const keys = Object.keys(payload).slice(0, 3)
    for (const key of keys) {
      const value = payload[key]
      if (value !== undefined && value !== null) parts.push(`${key}：${String(value)}`)
    }
  }
  return parts.join('　')
}
