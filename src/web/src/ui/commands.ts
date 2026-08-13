/**
 * 命令面板（Ctrl+K）的命令模型：导航、主题、成员切换与常用动作的统一入口。
 *
 * 只做纯数据与过滤逻辑，方便单测；DOM 交互由 CommandPalette 组件负责。
 * 过滤规则：无关键词时全量返回；有关键词时按 label / keywords / hint
 * 不区分大小写做包含匹配，保持零依赖（不引入拼音库）。
 */

export interface CommandItem {
  id: string
  /** 主标题，如「授权管理」 */
  label: string
  /** 右侧弱化说明，如分组名或动作解释 */
  hint: string
  /** 额外的匹配词（空格分隔），如英文/别名 */
  keywords: string
  icon: string
  run: () => void
}

export interface CommandGroup {
  name: string
  items: CommandItem[]
}

export function filterCommands(groups: CommandGroup[], rawQuery: string): CommandGroup[] {
  const query = rawQuery.trim().toLowerCase()
  if (!query) return groups.map(group => ({ ...group, items: [...group.items] }))

  const result: CommandGroup[] = []
  for (const group of groups) {
    const items = group.items.filter(item => {
      const haystack = `${item.label} ${item.keywords} ${item.hint}`.toLowerCase()
      return haystack.includes(query)
    })
    if (items.length > 0) result.push({ name: group.name, items })
  }
  return result
}

/** 把分组拍平成执行顺序列表，供键盘上下移动使用。 */
export function flattenCommands(groups: CommandGroup[]): CommandItem[] {
  return groups.flatMap(group => group.items)
}
