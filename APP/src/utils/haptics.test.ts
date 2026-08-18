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

  it('振动 API 调用失败时也静默降级', () => {
    const vibrate = vi.fn(() => {
      throw new Error('vibration denied')
    })
    vi.stubGlobal('navigator', { vibrate })
    expect(() => tapFeedback()).not.toThrow()
    expect(tapFeedback()).toBe(false)
  })
})
