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
    case 'SEVERE': return 'Severe'
    case 'WARNING': return 'Warning'
    case 'INFO': return 'Info'
    case 'TIP': return 'Tip'
    default: return 'Unclassified'
  }
}
