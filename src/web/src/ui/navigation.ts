/**
 * 侧栏导航模型：条目定义、门户过滤、分组与唯一化（HCT-447）。
 *
 * 只做纯数据逻辑，方便单测；DOM 渲染由 App.vue 负责。
 * 硬约束：同一 `view` 在任一门户下最多渲染一条导航——模板用
 * `session.currentView === item.view` 判定 active，一旦同一 view 出现
 * 两条（如「健康助手」与「本地助手」同指 `assistant`）就会同时高亮。
 */

import { MEMBER_VIEWS, SHARED_VIEWS, type PortalName, type ViewName } from '../store'

export interface NavItem {
  view: ViewName
  label: string
  icon: string
  group: string
  /**
   * 显式限定条目所属门户。共享视图（SHARED_VIEWS）会同时通过成员和
   * 管理员的通用过滤，因此每个门户的入口必须用本字段限定，
   * 否则两条会一起出现并双高亮。缺省表示仅按通用规则过滤。
   */
  portals?: readonly PortalName[]
}

// 管理员后台固定五组导航（HCT-439 阶段三）：
// 日常照护 / 证据录入 / 安全与洞察 / 账户安全 / 家庭洞察。
export const NAV_ITEMS: readonly NavItem[] = [
  { view: 'member-home', label: '我的家庭', icon: 'home', group: '我的照护' },
  { view: 'member-capture', label: '拍照录药', icon: 'scan', group: '我的照护' },
  { view: 'member-plans', label: '服药提醒', icon: 'plan', group: '我的照护' },
  { view: 'member-records', label: '我的记录', icon: 'compass', group: '我的照护' },
  { view: 'member-help', label: '使用帮助', icon: 'info', group: '我的照护' },
  { view: 'assistant', label: '健康助手', icon: 'assistant', group: '我的照护', portals: ['member'] },
  { view: 'overview', label: '家庭总览', icon: 'home', group: '日常照护' },
  { view: 'members', label: '成员档案', icon: 'members', group: '日常照护' },
  { view: 'plans', label: '健康计划', icon: 'plan', group: '日常照护' },
  { view: 'scan', label: '视觉扫描', icon: 'scan', group: '证据录入' },
  { view: 'review', label: '人工复核', icon: 'review', group: '证据录入' },
  { view: 'risks', label: '用药安全', icon: 'shield', group: '安全与洞察' },
  { view: 'graph', label: '健康图谱', icon: 'compass', group: '安全与洞察' },
  { view: 'assistant', label: '健康助手', icon: 'assistant', group: '安全与洞察', portals: ['admin'] },
  { view: 'face-credentials', label: '登录设置', icon: 'lock', group: '账户安全' },
  { view: 'bigscreen', label: '家庭大屏', icon: 'sun', group: '家庭洞察' },
  { view: 'digital-twin', label: '数字孪生', icon: 'sparkle', group: '家庭洞察', portals: ['admin'] },
]

/**
 * 计算某门户可见的导航条目：
 * 1. 先按 portals 显式限定过滤；
 * 2. 再套用成员（MEMBER_VIEWS + SHARED_VIEWS）/ 管理员（非 MEMBER_VIEWS）通用规则；
 * 3. 最后按 view 去重防御，保证 active 高亮唯一，即使未来条目配置出错。
 */
export function visibleNavItemsFor(portal: PortalName): NavItem[] {
  const filtered = NAV_ITEMS.filter(item => {
    if (item.portals && !item.portals.includes(portal)) return false
    return portal === 'member'
      ? MEMBER_VIEWS.includes(item.view) || SHARED_VIEWS.includes(item.view)
      : !MEMBER_VIEWS.includes(item.view)
  })
  const seen = new Set<ViewName>()
  const unique: NavItem[] = []
  for (const item of filtered) {
    if (seen.has(item.view)) continue
    seen.add(item.view)
    unique.push(item)
  }
  return unique
}

/** 保持条目原有顺序拍进分组，供侧栏按组渲染。 */
export function groupNavItems(items: readonly NavItem[]): Array<{ name: string; items: NavItem[] }> {
  const groups: Array<{ name: string; items: NavItem[] }> = []
  for (const item of items) {
    const group = groups.find(entry => entry.name === item.group)
    if (group) group.items.push(item)
    else groups.push({ name: item.group, items: [item] })
  }
  return groups
}

/** 当前视图对应的唯一导航条目；找不到时回落到第一条（面包屑兜底）。 */
export function activeNavItem(
  items: readonly NavItem[],
  currentView: ViewName,
): NavItem | undefined {
  return items.find(item => item.view === currentView) ?? items[0]
}
