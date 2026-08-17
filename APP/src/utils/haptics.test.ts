import { afterEach, describe, expect, it, vi } from 'vitest'

import { tapFeedback } from './haptics'

describe('触觉反馈', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('设备支持时调用 navigator.vibrate', () => {
    const vibrate = vi.fn().mockReturnValue(true)
    vi.stubGlobal('navigator', { vibrate })
    expect(tapFeedback([12, 60, 18])).toBe(true)
    expect(vibrate).toHaveBeenCalledWith([12, 60, 18])
  })

  it('设备不支持时静默降级', () => {
    vi.stubGlobal('navigator', {})
    expect(tapFeedback()).toBe(false)
  })
})
