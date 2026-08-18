import { beforeEach, describe, expect, it } from 'vitest'

import { focusRouteMain } from './accessibility'

describe('路由无障碍焦点', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('把焦点移到新页面主区域并补充可理解的页面名称', () => {
    document.body.innerHTML = '<main id="main"><h1>提醒</h1></main>'

    expect(focusRouteMain('提醒')).toBe(true)

    const main = document.querySelector<HTMLElement>('main')
    expect(document.activeElement).toBe(main)
    expect(main?.tabIndex).toBe(-1)
    expect(main?.getAttribute('aria-label')).toBe('提醒页面')
  })

  it('主区域尚未渲染时安全返回', () => {
    expect(focusRouteMain('提醒')).toBe(false)
  })
})
