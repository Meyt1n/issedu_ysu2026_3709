import type { Household } from '../api/types'

/**
 * HCT-439 阶段五：演示数据环境标识（轻量实现，不做数据迁移）。
 *
 * 只认显式标记：household 名称或创建者账号以 demo- / test- 开头，
 * 或名称带有「本地演示」「教学演示」字样。判断纯粹基于名称约定，
 * 不新增字段，也不修改任何存量数据。
 */
const DEMO_PREFIX = /^(demo-|test-)/i
const DEMO_NAME_MARKERS = ['本地演示', '教学演示']
const SHOW_DEMO_STORAGE_KEY = 'hct:show-demo-households'

export type DataEnvironment = 'DEMO' | 'LOCAL'

export function isDemoHousehold(household: Pick<Household, 'name' | 'created_by'>): boolean {
  if (DEMO_PREFIX.test(household.created_by) || DEMO_PREFIX.test(household.name)) return true
  return DEMO_NAME_MARKERS.some(marker => household.name.includes(marker))
}

export function householdEnvironment(
  household: Pick<Household, 'name' | 'created_by'>,
): DataEnvironment {
  return isDemoHousehold(household) ? 'DEMO' : 'LOCAL'
}

export function getShowDemoHouseholds(): boolean {
  try {
    return localStorage.getItem(SHOW_DEMO_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function setShowDemoHouseholds(show: boolean): void {
  try {
    localStorage.setItem(SHOW_DEMO_STORAGE_KEY, show ? '1' : '0')
  } catch {
    /* ignore quota / private mode */
  }
}

/**
 * 成员前台默认只展示 LOCAL 家庭；当成员名下只有演示家庭时保留原列表，
 * 避免演示账号进入空门户。管理员可强制显示演示家庭。
 */
export function memberVisibleHouseholds(households: Household[]): Household[] {
  if (getShowDemoHouseholds()) return households
  const locals = households.filter(household => !isDemoHousehold(household))
  return locals.length > 0 ? locals : households
}

/** 管理员后台的家庭选项文案：演示家庭追加显式标识。 */
export function householdOptionLabel(household: Household): string {
  return isDemoHousehold(household) ? `${household.name} · 演示数据` : household.name
}
