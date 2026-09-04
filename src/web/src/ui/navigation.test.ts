import { describe, expect, it } from 'vitest'

import { activeNavItem, NAV_ITEMS, visibleNavItemsFor } from './navigation'

describe('sidebar navigation uniqueness (HCT-447)', () => {
  it.each(['admin', 'member'] as const)(
    'renders the assistant entry exactly once in the %s portal',
    portal => {
      const items = visibleNavItemsFor(portal)
      const assistantItems = items.filter(item => item.view === 'assistant')
      expect(assistantItems).toHaveLength(1)
      expect(assistantItems[0]!.label).toBe('健康助手')
    },
  )

  it('places the assistant entry in the expected group per portal', () => {
    const adminAssistant = visibleNavItemsFor('admin').find(
      item => item.view === 'assistant',
    )
    const memberAssistant = visibleNavItemsFor('member').find(
      item => item.view === 'assistant',
    )
    expect(adminAssistant?.group).toBe('安全与洞察')
    expect(memberAssistant?.group).toBe('我的照护')
  })

  it.each(['admin', 'member'] as const)('never repeats a sidebar icon in the %s portal', portal => {
    const icons = visibleNavItemsFor(portal).map(item => item.icon)
    expect(new Set(icons).size).toBe(icons.length)
  })

  it('hides authorization management and keeps login settings in account security', () => {
    const items = visibleNavItemsFor('admin')
    const authorizations = items.find(item => item.view === 'authorizations')
    const credentials = items.find(item => item.view === 'face-credentials')
    const risks = items.find(item => item.view === 'risks')
    expect(authorizations).toBeUndefined()
    expect(credentials?.group).toBe('账户安全')
    expect(credentials?.icon).toBe('lock')
    expect(credentials?.icon).not.toBe(risks?.icon)
  })

  it.each(['admin', 'member'] as const)('never repeats a view in the %s portal', portal => {
    const views = visibleNavItemsFor(portal).map(item => item.view)
    expect(new Set(views).size).toBe(views.length)
  })

  it('keeps member portal limited to member and shared views', () => {
    const views = visibleNavItemsFor('member').map(item => item.view)
    expect(views).toEqual([
      'member-home',
      'member-capture',
      'member-plans',
      'member-records',
      'member-help',
      'assistant',
    ])
  })

  it('excludes member-only views and withdrawn lab pages from the admin portal', () => {
    const views = visibleNavItemsFor('admin').map(item => item.view)
    expect(views).not.toContain('member-home')
    expect(views).toContain('overview')
    expect(views).toContain('bigscreen')
    expect(views).not.toContain('knowledge')
    expect(NAV_ITEMS.map(item => item.view)).not.toContain('modellab')
    expect(NAV_ITEMS.map(item => item.view)).not.toContain('demo-lab')
    expect(NAV_ITEMS.some(item => item.label === '模型实验室')).toBe(false)
    expect(NAV_ITEMS.some(item => item.label === '演示造数')).toBe(false)
  })

  it('exposes the family digital twin only in the admin portal', () => {
    const adminTwin = visibleNavItemsFor('admin').find(
      item => item.view === 'digital-twin',
    )
    expect(adminTwin?.label).toBe('数字孪生')
    expect(adminTwin?.group).toBe('家庭洞察')
    expect(visibleNavItemsFor('member').some(item => item.view === 'digital-twin')).toBe(false)
  })

  it('deduplicates by view even if a future entry forgets portal scoping', () => {
    // NAV_ITEMS 故意包含两条 assistant（成员/管理员各一条）；
    // 即使 portals 限定失效，visibleNavItemsFor 的去重兜底也必须只留一条。
    const assistantDefinitions = NAV_ITEMS.filter(item => item.view === 'assistant')
    expect(assistantDefinitions.length).toBeGreaterThanOrEqual(2)
    for (const portal of ['admin', 'member'] as const) {
      const views = visibleNavItemsFor(portal).map(item => item.view)
      expect(views.filter(view => view === 'assistant')).toHaveLength(1)
    }
  })
})

describe('active navigation selection', () => {
  it('marks exactly one entry active when the assistant view is open', () => {
    for (const portal of ['admin', 'member'] as const) {
      const items = visibleNavItemsFor(portal)
      const activeItems = items.filter(item => item.view === 'assistant')
      expect(activeItems).toHaveLength(1)
      expect(activeNavItem(items, 'assistant')).toBe(activeItems[0])
    }
  })

  it('falls back to the first entry when the current view is not visible', () => {
    const items = visibleNavItemsFor('member')
    expect(activeNavItem(items, 'overview')).toBe(items[0])
  })
})
