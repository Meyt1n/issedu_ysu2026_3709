import type { RiskAlert, RiskLevel, RiskSourceEvent } from '../api/types'

export interface RiskCardModel {
  ruleId: string
  level: RiskLevel
  message: string
  sourceCount: number
  createdAt: string | null
}

export interface RiskDetailModel {
  alert: RiskCardModel
  sourceEvents: RiskSourceEvent[]
}

export function toRiskCardModel(alert: RiskAlert): RiskCardModel {
  return {
    ruleId: alert.rule_id,
    level: alert.level,
    message: alert.message,
    sourceCount: alert.source_event_ids.length,
    createdAt: alert.created_at,
  }
}

export function riskLevelLabel(level: RiskLevel): string {
  switch (level) {
    case 'SEVERE': return '严重'
    case 'WARNING': return '警告'
    case 'INFO': return '提示'
    case 'TIP': return '建议'
    default: return '未分级'
  }
}
