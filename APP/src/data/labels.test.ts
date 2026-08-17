import { describe, expect, it } from 'vitest'

import {
  memberRoleLabel,
  recognitionStatusLabel,
  riskLevelLabel,
  riskLevelTone,
  taskLevelLabel,
  taskLevelTone,
} from './labels'

describe('等级与状态文案映射', () => {
  it('提醒四级与主仓库命名对应（INFO/GENERAL/HIGH/URGENT）', () => {
    expect(taskLevelLabel('INFO')).toBe('信息')
    expect(taskLevelLabel('GENERAL')).toBe('一般')
    expect(taskLevelLabel('HIGH')).toBe('重要')
    expect(taskLevelLabel('URGENT')).toBe('紧急')
    expect(taskLevelTone('URGENT')).toBe('danger')
  })

  it('风险四级与主仓库 API RiskLevel 对应（SEVERE/WARNING/INFO/TIP）', () => {
    expect(riskLevelLabel('SEVERE')).toBe('严重')
    expect(riskLevelLabel('WARNING')).toBe('较高')
    expect(riskLevelLabel('INFO')).toBe('一般')
    expect(riskLevelLabel('TIP')).toBe('提示')
    expect(riskLevelTone('SEVERE')).toBe('danger')
  })

  it('未知等级回退为“未分级”，不猜测语义', () => {
    expect(riskLevelLabel('SOMETHING_NEW')).toBe('未分级')
    expect(riskLevelTone('SOMETHING_NEW')).toBe('neutral')
  })

  it('识别四态与主仓库 FR-03 对应', () => {
    expect(recognitionStatusLabel('MATCHED')).toBe('已匹配')
    expect(recognitionStatusLabel('CONFLICT')).toBe('证据冲突')
    expect(recognitionStatusLabel('UNKNOWN')).toBe('未知药品')
    expect(recognitionStatusLabel('REVIEW')).toBe('需人工复核')
  })

  it('成员角色映射', () => {
    expect(memberRoleLabel('SELF')).toBe('本人')
    expect(memberRoleLabel('DEPENDENT')).toBe('被照护成员')
    expect(memberRoleLabel('CAREGIVER')).toBe('照护者')
  })
})
