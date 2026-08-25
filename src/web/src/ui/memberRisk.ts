/**
 * HCT-405 A2：成员前台风险提醒文案。
 *
 * 后端规则消息仍保留药品/过敏事实；成员前台额外做生活化包装，
 * 绝不展示 rule_id、指纹或其它内部代号。
 */

const INTERNAL_TOKENS = [
  'allergy_conflict',
  'duplicate_ingredient',
  'interaction',
  'expiry_check',
  'low_stock',
  'risk_fingerprint',
  'rule_id',
  'SEVERE',
  'WARNING',
]

export interface MemberRiskInput {
  rule_id: string
  message: string
  level?: string
}

export function memberRiskLevelLabel(level: string | null | undefined): string {
  switch (level) {
    case 'SEVERE':
      return '重要'
    case 'WARNING':
      return '提醒'
    case 'INFO':
      return '提示'
    case 'TIP':
      return '建议'
    default:
      return '提醒'
  }
}

export function memberRiskMessage(alert: MemberRiskInput): string {
  const raw = (alert.message || '').trim().replace(/[。．.]+$/u, '')
  switch (alert.rule_id) {
    case 'allergy_conflict':
      return raw
        ? `${raw}。请先问家人或医生，不要自行停药或加药。`
        : '请和家人一起核对：这条药品记录可能和已知过敏有关。'
    case 'duplicate_ingredient':
      return raw
        ? `${raw}。请和家人一起核对是否重复用药。`
        : '请和家人一起核对：多条记录里可能有相同成分。'
    case 'interaction':
      return raw
        ? `${raw}。请和家人一起对照说明书或医嘱。`
        : '请和家人一起核对这两种药品是否适合一起使用。'
    case 'expiry_check':
      return raw
        ? `${raw}。请先问家人怎么处理。`
        : '请留意：有药品可能快过期或已经过期。'
    case 'low_stock':
      return raw
        ? `${raw}。可以告诉家人及时补充。`
        : '请留意：有药品库存不多了。'
    default:
      return raw || '请和家人一起核对这条提醒。'
  }
}

/** 回归：文案中不得出现内部规则码或英文级别。 */
export function memberRiskTextIsSafe(text: string): boolean {
  return !INTERNAL_TOKENS.some(token => text.includes(token))
}
