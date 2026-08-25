import type { Authorization, AuthorizationAction } from '../api/types'
import { isAuthorizationActive } from './authorizationView'

/**
 * 与 HCT-102 冻结契约一致的 purpose 代码模式。
 * 底层始终提交 ASCII 代码；本模块只负责给家庭用户可读的标签。
 */
export const PURPOSE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/

export interface PurposeOption {
  code: string
  label: string
  description: string
}

/** 常用授权用途：展示用标签 + 底层代码。访问时服务端仍按代码精确匹配。 */
export const PURPOSE_OPTIONS: PurposeOption[] = [
  {
    code: 'family-care',
    label: '家庭日常照护',
    description: '子女或家人日常查看健康记录、协助照护',
  },
  {
    code: 'emergency-care',
    label: '紧急照护',
    description: '突发情况下紧急联系人了解健康状况',
  },
  {
    code: 'temporary-care',
    label: '临时协助',
    description: '保姆、护工等短期照护协助，到期自动失效',
  },
]

export function purposeLabel(code: string): string {
  return PURPOSE_OPTIONS.find(option => option.code === code)?.label ?? code
}

export interface AuthorizationTemplate {
  id: string
  name: string
  description: string
  dataFields: string[]
  actions: AuthorizationAction[]
  purpose: string
  suggestedDays: number
}

/**
 * 家庭常见场景的授权模板（页面设计基线 §3.9 的「预设」）。
 * 约束：默认最小权限——模板一律不含 WRITE_EVENTS，字段/动作只来自服务端已支持集合，
 * 套用后仍可逐项修改。
 */
export const AUTHORIZATION_TEMPLATES: AuthorizationTemplate[] = [
  {
    id: 'daily-family-care',
    name: '子女日常照护',
    description: '可查看已确认健康事件和风险回执，并替长辈确认「风险已知晓」。建议 30 天，到期可续。',
    dataFields: ['health_events', 'risk_alerts'],
    actions: ['READ_EVENTS', 'ACK_RISK'],
    purpose: 'family-care',
    suggestedDays: 30,
  },
  {
    id: 'emergency-readonly',
    name: '紧急联系人只读',
    description: '只能查看已确认健康事件，便于紧急情况快速了解现状，不能做任何修改。建议 90 天。',
    dataFields: ['health_events'],
    actions: ['READ_EVENTS'],
    purpose: 'emergency-care',
    suggestedDays: 90,
  },
  {
    id: 'temporary-helper',
    name: '临时协助（保姆/护工）',
    description: '短期查看已确认健康事件，7 天后自动失效，随时可提前撤回。',
    dataFields: ['health_events'],
    actions: ['READ_EVENTS'],
    purpose: 'temporary-care',
    suggestedDays: 7,
  },
]

export interface TemplateDraft {
  dataFields: string[]
  actions: AuthorizationAction[]
  purpose: string
  /** ISO 字符串，套用模板时按 suggestedDays 从当前时间推算。 */
  validUntil: string
}

export function applyTemplate(
  template: AuthorizationTemplate,
  now: Date = new Date(),
): TemplateDraft {
  const validUntil = new Date(now)
  validUntil.setDate(validUntil.getDate() + template.suggestedDays)
  return {
    dataFields: [...template.dataFields],
    actions: [...template.actions],
    purpose: template.purpose,
    validUntil: validUntil.toISOString(),
  }
}

/** 剩余天数（向上取整）；已过期返回 0，非法时间返回 null。 */
export function daysUntilExpiry(validUntil: string, now: Date = new Date()): number | null {
  const timestamp = Date.parse(validUntil)
  if (!Number.isFinite(timestamp)) return null
  const diff = timestamp - now.getTime()
  if (diff <= 0) return 0
  return Math.ceil(diff / 86_400_000)
}

const EXPIRING_SOON_DAYS = 7

/** 仍在生效且 7 天内到期的授权需要在列表中提醒管理员续期或放手到期。 */
export function isExpiringSoon(authorization: Authorization, now: Date = new Date()): boolean {
  if (!isAuthorizationActive(authorization, now)) return false
  const days = daysUntilExpiry(authorization.valid_until, now)
  return days !== null && days <= EXPIRING_SOON_DAYS
}

export interface HandoffInput {
  granteeActorId: string
  memberName: string
  fieldLabels: string[]
  actionLabels: string[]
  purposeCode: string
  validUntilText: string
}

/**
 * 创建成功后给对方的交接说明。管理员可直接复制发给被授权的家人/照护者，
 * 告诉对方用哪个账号登录、登录页用途代码填什么、什么时候过期。
 */
export function buildHandoffText(input: HandoffInput): string {
  const label = purposeLabel(input.purposeCode)
  const purposeText =
    label === input.purposeCode ? input.purposeCode : `${input.purposeCode}（${label}）`
  return [
    '【家健镜授权说明】',
    `照护者账号：${input.granteeActorId}`,
    `可以查看：${input.memberName} 的 ${input.fieldLabels.join('、')}`,
    `可以进行：${input.actionLabels.join('、')}`,
    `登录时「访问用途代码」请填写：${purposeText}`,
    `有效期至：${input.validUntilText}`,
    '提示：请用上述账号登录家健镜；用途代码必须与授权一致才能看到内容。家庭管理员可随时撤回这条授权。',
  ].join('\n')
}

// ── 审计记录去技术化 ────────────────────────────────────────────────

export const AUDIT_OPERATION_LABELS: Record<string, string> = {
  CREATE: '新建授权',
  UPDATE: '修改授权',
  REVOKE: '撤回授权',
  ACCESS: '访问数据',
  RISK_ACK: '确认风险',
  APPEND_EVENT: '记录健康事件',
  AUTHENTICATION: '登录验证',
  ERASURE: '数据删除',
  DELETE: '数据清理',
  READ: '数据读取',
}

export function auditOperationLabel(operation: string): string {
  return AUDIT_OPERATION_LABELS[operation] ?? operation
}

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  READ_EVENTS: '查看已确认事件',
  WRITE_EVENTS: '追加已确认事件',
  ACK_RISK: '确认风险已知晓',
  WRITE_EVIDENCE: '上传识别证据',
  GRANT: '授予权限',
  LOGIN: '登录',
}

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action
}

export const AUDIT_OUTCOME_LABELS: Record<string, string> = {
  ALLOWED: '已允许',
  DENIED: '已拒绝',
  SUCCESS: '成功',
  FAILED: '失败',
}

export function auditOutcomeLabel(outcome: string): string {
  return AUDIT_OUTCOME_LABELS[outcome] ?? outcome
}

export const AUDIT_REASON_LABELS: Record<string, string> = {
  AUTHORIZATION_NOT_FOUND: '没有匹配的授权',
  CONSENT_REVOKED: '授权已被撤回',
  AUTHORIZATION_NOT_ACTIVE: '授权尚未生效',
  AUTHORIZATION_EXPIRED: '授权已过期',
  ACTION_NOT_GRANTED: '该操作未被授权',
  FIELD_NOT_GRANTED: '该字段未被授权',
  PURPOSE_REQUIRED: '访问时未填写用途代码',
  PURPOSE_MISMATCH: '用途与授权不一致',
  OWNER_PURPOSE_REQUIRED: '管理员访问也需填写用途',
  SELF_MEMBER_SCOPE: '本人查看自己的记录',
  SELF_MEMBER_CAPTURE: '本人上传自己的证据',
  AUTHENTICATED: '登录成功',
  AUTH_FAILED: '登录失败',
  RATE_LIMITED: '尝试过于频繁，已暂时限制',
}

export function auditReasonLabel(reason: string | null | undefined): string {
  if (!reason) return ''
  return AUDIT_REASON_LABELS[reason] ?? reason
}
