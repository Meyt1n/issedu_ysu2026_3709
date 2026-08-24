import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createVisionTaskPolling, visionTaskStatusLabel } from './useVisionTaskPolling'
import type { VisionTaskStatusSnapshot } from '@/data/types'

function snapshot(patch: Partial<VisionTaskStatusSnapshot> = {}): VisionTaskStatusSnapshot {
  return {
    taskId: 'task-1',
    status: 'queued',
    terminal: false,
    errorCode: null,
    errorMessage: null,
    modelVersion: null,
    createdAt: '2026-08-22T08:00:00Z',
    nextStep: '排队中',
    ...patch,
  }
}

describe('视觉任务状态轮询（MOB-132）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('立即回查第一次，未终态时按退避节奏续查', async () => {
    const fetchStatus = vi.fn()
      .mockResolvedValueOnce(snapshot({ status: 'queued' }))
      .mockResolvedValueOnce(snapshot({ status: 'running' }))
      .mockResolvedValue(snapshot({ status: 'succeeded', terminal: true }))
    const polling = createVisionTaskPolling(fetchStatus, { initialDelayMs: 1000, factor: 2, maxDelayMs: 8000 })

    polling.start('task-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchStatus).toHaveBeenCalledTimes(1)
    expect(polling.state.value.phase).toBe('polling')
    expect(polling.state.value.nextDelayMs).toBe(1000)

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchStatus).toHaveBeenCalledTimes(2)
    // 第二次之后退避翻倍
    expect(polling.state.value.nextDelayMs).toBe(2000)

    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchStatus).toHaveBeenCalledTimes(3)
    expect(polling.state.value.phase).toBe('terminal')
    expect(polling.state.value.snapshot?.status).toBe('succeeded')
    expect(polling.state.value.nextDelayMs).toBeNull()
    // 终态后不再排定时器
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchStatus).toHaveBeenCalledTimes(3)
  })

  it('重试回查复用同一 taskId，绝不重复创建任务', async () => {
    const fetchStatus = vi.fn().mockResolvedValue(snapshot({ status: 'running' }))
    const polling = createVisionTaskPolling(fetchStatus, { initialDelayMs: 100, factor: 2, maxDelayMs: 200, maxAttempts: 2 })

    polling.start('task-1')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(100)
    expect(polling.state.value.phase).toBe('exhausted')

    polling.checkNow()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchStatus).toHaveBeenCalledTimes(3)
    expect(fetchStatus.mock.calls.every(call => call[0] === 'task-1')).toBe(true)
  })

  it('回查抛错按同一预算退避，预算耗尽进入 exhausted 并保留错误信息', async () => {
    const fetchStatus = vi.fn().mockRejectedValue(new Error('网络中断'))
    const polling = createVisionTaskPolling(fetchStatus, { initialDelayMs: 50, factor: 2, maxDelayMs: 100, maxAttempts: 3 })

    polling.start('task-1')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(50)
    await vi.advanceTimersByTimeAsync(100)
    expect(polling.state.value.phase).toBe('exhausted')
    expect(polling.state.value.lastError).toContain('网络中断')
    expect(polling.state.value.attempts).toBe(3)
  })

  it('切后台停止并清理定时器，回前台立即回查一次再续轮询', async () => {
    const fetchStatus = vi.fn().mockResolvedValue(snapshot({ status: 'running' }))
    const polling = createVisionTaskPolling(fetchStatus, { initialDelayMs: 1000, factor: 2, maxDelayMs: 8000, maxAttempts: 10 })
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)

    polling.start('task-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchStatus).toHaveBeenCalledTimes(1)

    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    const callsAtHidden = fetchStatus.mock.calls.length
    await vi.advanceTimersByTimeAsync(60_000)
    // 后台期间不再发请求
    expect(fetchStatus.mock.calls.length).toBe(callsAtHidden)
    expect(polling.state.value.nextDelayMs).toBeNull()

    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchStatus.mock.calls.length).toBe(callsAtHidden + 1)
    expect(polling.state.value.phase).toBe('polling')
    polling.dispose()
  })

  it('stop 清理定时器，dispose 移除可见性监听', async () => {
    const fetchStatus = vi.fn().mockResolvedValue(snapshot({ status: 'running' }))
    const polling = createVisionTaskPolling(fetchStatus, { initialDelayMs: 1000, factor: 2, maxDelayMs: 8000 })
    const hiddenSpy = vi.spyOn(document, 'hidden', 'get')

    polling.start('task-1')
    await vi.advanceTimersByTimeAsync(0)
    polling.stop()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchStatus).toHaveBeenCalledTimes(1)

    polling.dispose()
    hiddenSpy.mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(0)
    // dispose 后可见性变化不再触发回查
    expect(fetchStatus).toHaveBeenCalledTimes(1)
  })

  it('未知状态停止自动轮询且不当作成功', async () => {
    const fetchStatus = vi.fn().mockResolvedValue(snapshot({ status: 'weird-new-state', terminal: true }))
    const polling = createVisionTaskPolling(fetchStatus, { initialDelayMs: 1000, factor: 2, maxDelayMs: 8000 })

    polling.start('task-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(polling.state.value.phase).toBe('terminal')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchStatus).toHaveBeenCalledTimes(1)
    expect(visionTaskStatusLabel('weird-new-state')).toBe('未知状态（weird-new-state）')
    expect(visionTaskStatusLabel('succeeded')).toBe('已完成')
  })
})
