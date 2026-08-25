import { describe, expect, it } from 'vitest'

import { activeNavItem, NAV_ITEMS, visibleNavItemsFor } from './navigation'

describe('sidebar navigation uniqueness (HCT-447)', () => {
  it.each(['admin', 'member'] as const)(
    'renders the assistant entry exactly once in the %s portal',
    portal => {
      const items = visibleNavItemsFor(portal, true)
      const assistantItems = items.filter(item => item.view === 'assistant')
      expect(assistantItems).toHaveLength(1)
      expect(assistantItems[0]!.label).toBe('健康助手')
    },
  )

  it('places the assistant entry in the expected group per portal', () => {
    const adminAssistant = visibleNavItemsFor('admin', true).find(
      item => item.view === 'assistant',
    )
    const memberAssistant = visibleNavItemsFor('member', true).find(
      item => item.view === 'assistant',
    )
    expect(adminAssistant?.group).toBe('安全与洞察')
    expect(memberAssistant?.group).toBe('我的照护')
  })

  it.each([
    ['admin', true],
    ['admin', false],
    ['member', true],
    ['member', false],
  ] as const)('never repeats a view in the %s portal (advanced lab: %s)', (portal, lab) => {
    const views = visibleNavItemsFor(portal, lab).map(item => item.view)
    expect(new Set(views).size).toBe(views.length)
  })

  it('keeps member portal limited to member and shared views', () => {
    const views = visibleNavItemsFor('member', true).map(item => item.view)
    expect(views).toEqual([
      'member-home',
      'member-capture',
      'member-plans',
      'member-records',
      'member-help',
      'assistant',
    ])
  })

  it('excludes member-only views and the lab flag from the admin portal', () => {
    const views = visibleNavItemsFor('admin', false).map(item => item.view)
    expect(views).not.toContain('member-home')
    expect(views).not.toContain('modellab')
    expect(views).toContain('overview')
  })

  it('deduplicates by view even if a future entry forgets portal scoping', () => {
    // NAV_ITEMS 故意包含两条 assistant（成员/管理员各一条）；
    // 即使 portals 限定失效，visibleNavItemsFor 的去重兜底也必须只留一条。
    const assistantDefinitions = NAV_ITEMS.filter(item => item.view === 'assistant')
    expect(assistantDefinitions.length).toBeGreaterThanOrEqual(2)
    for (const portal of ['admin', 'member'] as const) {
      const views = visibleNavItemsFor(portal, true).map(item => item.view)
      expect(views.filter(view => view === 'assistant')).toHaveLength(1)
    }
  })
})

describe('active navigation selection', () => {
  it('marks exactly one entry active when the assistant view is open', () => {
    for (const portal of ['admin', 'member'] as const) {
      const items = visibleNavItemsFor(portal, true)
      const activeItems = items.filter(item => item.view === 'assistant')
      expect(activeItems).toHaveLength(1)
      expect(activeNavItem(items, 'assistant')).toBe(activeItems[0])
    }
  })

  it('falls back to the first entry when the current view is not visible', () => {
    const items = visibleNavItemsFor('member', true)
    expect(activeNavItem(items, 'overview')).toBe(items[0])
  })
})
