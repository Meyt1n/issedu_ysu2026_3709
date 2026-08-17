import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { clearToasts, dismissToast, showToast, useToasts } from './useToast'

describe('轻提示队列', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    clearToasts()
  })

  afterEach(() => {
    clearToasts()
    vi.useRealTimers()
  })

  it('弹出后进入队列，到时自动消失', () => {
    const { toasts } = useToasts()
    showToast('已确认：早间服药', 'success', 2000)
    expect(toasts.length).toBe(1)
    expect(toasts[0]!.text).toBe('已确认：早间服药')
    expect(toasts[0]!.tone).toBe('success')

    vi.advanceTimersByTime(2100)
    expect(toasts.length).toBe(0)
  })

  it('可手动关闭', () => {
    const { toasts } = useToasts()
    const id = showToast('提示', 'info')
    dismissToast(id)
    expect(toasts.length).toBe(0)
  })

  it('同屏最多保留 3 条，超出移除最旧', () => {
    const { toasts } = useToasts()
    showToast('一')
    showToast('二')
    showToast('三')
    showToast('四')
    expect(toasts.length).toBe(3)
    expect(toasts.map(t => t.text)).toEqual(['二', '三', '四'])
  })
})
