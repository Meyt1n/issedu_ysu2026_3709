import { describe, expect, it } from 'vitest'

import {
  memberRiskLevelLabel,
  memberRiskMessage,
  memberRiskTextIsSafe,
} from './memberRisk'

describe('成员前台风险文案（HCT-405 A2）', () => {
  it('把严重级别改成生活化标签，不暴露 SEVERE', () => {
    expect(memberRiskLevelLabel('SEVERE')).toBe('重要')
    expect(memberRiskLevelLabel('WARNING')).toBe('提醒')
    expect(memberRiskTextIsSafe(memberRiskLevelLabel('SEVERE'))).toBe(true)
  })

  it('过敏冲突保留事实并追加求助指引', () => {
    const text = memberRiskMessage({
      rule_id: 'allergy_conflict',
      message: '药品 aspirin 与过敏 aspirin 冲突',
      level: 'SEVERE',
    })
    expect(text).toContain('aspirin')
    expect(text).toContain('家人或医生')
    expect(memberRiskTextIsSafe(text)).toBe(true)
  })

  it('未知规则不回显 rule_id', () => {
    const text = memberRiskMessage({
      rule_id: 'future_rule_xyz',
      message: '',
      level: 'INFO',
    })
    expect(text).not.toContain('future_rule_xyz')
    expect(memberRiskTextIsSafe(text)).toBe(true)
  })
})
