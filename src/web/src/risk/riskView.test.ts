import { describe, expect, it } from 'vitest'

import type { RiskAlert } from '../api/types'
import { riskLevelLabel, toRiskCardModel } from './riskView'

const alert: RiskAlert = {
  rule_id: 'expired-medication',
  level: 'WARNING',
  message: 'A confirmed fact matches an expiry rule.',
  source_event_ids: ['event-1', 'event-2'],
  created_at: '2026-08-08T08:00:00Z',
}

describe('risk card view model', () => {
  it('maps only desensitized risk metadata for the collapsed card', () => {
    expect(toRiskCardModel(alert)).toEqual({
      ruleId: 'expired-medication',
      level: 'WARNING',
      message: 'A confirmed fact matches an expiry rule.',
      sourceCount: 2,
      createdAt: '2026-08-08T08:00:00Z',
    })
  })

  it('labels known and unknown levels without inventing severity', () => {
    expect(riskLevelLabel('SEVERE')).toBe('Severe')
    expect(riskLevelLabel('future-level')).toBe('Unclassified')
  })
})
