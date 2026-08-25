import { describe, expect, it } from 'vitest'

import type { Household } from '../api/types'
import {
  householdEnvironment,
  householdOptionLabel,
  isDemoHousehold,
  memberVisibleHouseholds,
} from './demoData'

function household(name: string, createdBy: string, id = name): Household {
  return { id, name, created_by: createdBy, created_at: '2026-08-25T00:00:00Z' }
}

describe('演示数据环境标识（HCT-439 阶段五）', () => {
  it('demo-/test- 前缀的创建者或名称被识别为 DEMO', () => {
    expect(isDemoHousehold(household('爷爷奶奶家', 'demo-parent'))).toBe(true)
    expect(isDemoHousehold(household('test-家庭', 'parent-1'))).toBe(true)
    expect(isDemoHousehold(household('demo-household', 'parent-1'))).toBe(true)
    expect(householdEnvironment(household('爷爷奶奶家', 'demo-parent'))).toBe('DEMO')
  })

  it('名称包含「本地演示」「教学演示」也被识别为 DEMO', () => {
    expect(isDemoHousehold(household('爷爷奶奶家（本地演示）', 'parent-1'))).toBe(true)
    expect(isDemoHousehold(household('教学演示家庭', 'parent-1'))).toBe(true)
  })

  it('普通家庭是 LOCAL，不受误伤', () => {
    expect(isDemoHousehold(household('爷爷奶奶家', 'parent-1'))).toBe(false)
    // demo/test 出现在中间不算显式标记，避免误删真实家庭
    expect(isDemoHousehold(household('小test家', 'parent-1'))).toBe(false)
    expect(isDemoHousehold(household('家庭demo', 'my-demo-account'))).toBe(false)
    expect(householdEnvironment(household('爷爷奶奶家', 'parent-1'))).toBe('LOCAL')
  })

  it('成员前台默认过滤 DEMO 家庭，但演示账号只有演示家庭时不清空', () => {
    const local = household('爷爷奶奶家', 'parent-1', 'h-local')
    const demo = household('爷爷奶奶家（本地演示）', 'demo-parent', 'h-demo')
    expect(memberVisibleHouseholds([local, demo])).toEqual([local])
    expect(memberVisibleHouseholds([demo])).toEqual([demo])
    expect(memberVisibleHouseholds([])).toEqual([])
  })

  it('管理员选项为演示家庭追加标识', () => {
    expect(householdOptionLabel(household('爷爷奶奶家（本地演示）', 'demo-parent'))).toContain(
      '演示数据',
    )
    expect(householdOptionLabel(household('爷爷奶奶家', 'parent-1'))).toBe('爷爷奶奶家')
  })
})
