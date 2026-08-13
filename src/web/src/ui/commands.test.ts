import { describe, expect, it } from 'vitest'

import { filterCommands, flattenCommands, type CommandGroup } from './commands'

function fixture(): CommandGroup[] {
  const noop = (): void => undefined
  return [
    {
      name: '页面',
      items: [
        { id: 'nav:risks', label: '用药安全', hint: '安全与洞察', keywords: 'risks safety', icon: 'shield', run: noop },
        { id: 'nav:auth', label: '授权管理', hint: '家庭与研发', keywords: 'authorization grant', icon: 'key', run: noop },
      ],
    },
    {
      name: '主题',
      items: [
        { id: 'theme:warm', label: '暖阳纸笺', hint: '切换主题', keywords: 'theme warm', icon: 'palette', run: noop },
      ],
    },
  ]
}

describe('command palette model', () => {
  it('returns every group untouched when the query is blank', () => {
    const groups = filterCommands(fixture(), '   ')
    expect(groups).toHaveLength(2)
    expect(flattenCommands(groups).map(item => item.id)).toEqual([
      'nav:risks',
      'nav:auth',
      'theme:warm',
    ])
  })

  it('matches against label, keywords and hint case-insensitively', () => {
    expect(flattenCommands(filterCommands(fixture(), '授权')).map(i => i.id)).toEqual(['nav:auth'])
    expect(flattenCommands(filterCommands(fixture(), 'GRANT')).map(i => i.id)).toEqual(['nav:auth'])
    expect(flattenCommands(filterCommands(fixture(), '安全')).map(i => i.id)).toEqual(['nav:risks'])
    expect(flattenCommands(filterCommands(fixture(), '切换主题')).map(i => i.id)).toEqual(['theme:warm'])
  })

  it('drops empty groups and returns nothing for a hopeless query', () => {
    const groups = filterCommands(fixture(), '购药')
    expect(groups).toHaveLength(0)
    expect(flattenCommands(groups)).toHaveLength(0)
  })
})
