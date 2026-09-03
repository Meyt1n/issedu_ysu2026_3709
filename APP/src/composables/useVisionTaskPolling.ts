import { ref } from 'vue'

import type { VisionTaskStatusSnapshot } from '@/data/types'

/**
 * MOB-132：视觉任务状态回查轮询。
 *
 * 有上限的指数退避：初始 1s、×1.6、封顶 8s、最多 12 次。
 * 到达终态、手动 stop、页面离开、切换会话/成员或切到后台时停止并清理；
 * 回前台先立即回查一次再续轮询。回查失败计入同一退避预算，
 * 预算耗尽后进入 exhausted 态，由页面提供"重试回查"（复用同一 taskId）。
 */

export interface VisionTaskPollingOptions {
  initialDelayMs?: number
  factor?: number
  maxDelayMs?: number
  maxAttempts?: number
  /** 注入定时器便于测试；默认使用全局 setTimeout。 */
  schedule?: (callback: () => void, delayMs: number) => () => void
  now?: () => Date
}

export interface VisionTaskPollingState {
  phase: 'idle' | 'polling' | 'terminal' | 'exhausted'
  snapshot: VisionTaskStatusSnapshot | null
  attempts: number
  /** 下一次自动回查的等待毫秒数；null 表示当前不会自动回查。 */
  nextDelayMs: number | null
  lastCheckedAt: string | null
  lastError: string | null
}

const DEFAULT_INITIAL_DELAY_MS = 1_000
const DEFAULT_FACTOR = 1.6
const DEFAULT_MAX_DELAY_MS = 8_000
const DEFAULT_MAX_ATTEMPTS = 12

export function createVisionTaskPolling(
  fetchStatus: (taskId: string) => Promise<VisionTaskStatusSnapshot>,
  options: VisionTaskPollingOptions = {},
) {
  const {
    initialDelayMs = DEFAULT_INITIAL_DELAY_MS,
    factor = DEFAULT_FACTOR,
    maxDelayMs = DEFAULT_MAX_DELAY_MS,
    maxAttempts = DEFAULT_MAX_ATTEMPTS,
    schedule = (callback, delayMs) => {
      const timer = setTimeout(callback, delayMs)
      return () => clearTimeout(timer)
    },
    now = () => new Date(),
  } = options

  const state = ref<VisionTaskPollingState>({
    phase: 'idle',
    snapshot: null,
    attempts: 0,
    nextDelayMs: null,
    lastCheckedAt: null,
    lastError: null,
  })

  let taskId: string | null = null
  let cancelScheduled: (() => void) | null = null
  let attempt = 0
  let running = false
  /** 最近一次轮询的任务；预算耗尽后的"重试回查"复用它，绝不换任务。 */
  let lastTaskId: string | null = null
  /** 切后台前正在轮询的任务；回前台后立即回查一次再续轮询。 */
  let pausedTaskId: string | null = null

  function cancelTimer(): void {
    cancelScheduled?.()
    cancelScheduled = null
  }

  function nextDelay(): number {
    return Math.min(maxDelayMs, Math.round(initialDelayMs * factor ** Math.max(0, attempt - 1)))
  }

  async function pollOnce(): Promise<void> {
    if (!running || !taskId) return
    const id = taskId
    attempt += 1
    try {
      const snapshot = await fetchStatus(id)
      if (!running || taskId !== id) return
      state.value = {
        phase: snapshot.terminal ? 'terminal' : 'polling',
        snapshot,
        attempts: attempt,
        nextDelayMs: snapshot.terminal ? null : attempt >= maxAttempts ? null : nextDelay(),
        lastCheckedAt: now().toISOString(),
        lastError: null,
      }
      if (snapshot.terminal || attempt >= maxAttempts) {
        if (!snapshot.terminal) state.value = { ...state.value, phase: 'exhausted' }
        stopInternal()
        return
      }
      scheduleNext()
    } catch (cause) {
      if (!running || taskId !== id) return
      const message = cause instanceof Error ? cause.message : String(cause)
      if (attempt >= maxAttempts) {
        state.value = {
          phase: 'exhausted',
          snapshot: state.value.snapshot,
          attempts: attempt,
          nextDelayMs: null,
          lastCheckedAt: now().toISOString(),
          lastError: message,
        }
        stopInternal()
        return
      }
      state.value = {
        phase: 'polling',
        snapshot: state.value.snapshot,
        attempts: attempt,
        nextDelayMs: nextDelay(),
        lastCheckedAt: state.value.lastCheckedAt,
        lastError: message,
      }
      scheduleNext()
    }
  }

  function scheduleNext(): void {
    cancelTimer()
    const delay = nextDelay()
    state.value = { ...state.value, nextDelayMs: delay }
    cancelScheduled = schedule(() => {
      void pollOnce()
    }, delay)
  }

  function stopInternal(): void {
    running = false
    taskId = null
    cancelTimer()
    if (state.value.phase === 'polling' || state.value.phase === 'idle') {
      state.value = { ...state.value, nextDelayMs: null }
    }
  }

  /** 停止轮询并清理定时器；终态结果保留在 state 里供页面展示。 */
  function stop(): void {
    stopInternal()
    state.value = { ...state.value, nextDelayMs: null }
  }

  /** 开始回查一个任务；立即查第一次，再按退避续查。 */
  function start(id: string): void {
    stopInternal()
    taskId = id
    lastTaskId = id
    pausedTaskId = null
    attempt = 0
    running = true
    state.value = {
      phase: 'polling',
      snapshot: null,
      attempts: 0,
      nextDelayMs: 0,
      lastCheckedAt: null,
      lastError: null,
    }
    void pollOnce()
  }

  /**
   * 手动"重试回查 / 立即回查"：复用当前或指定的同一 taskId，
   * 不新建任务；预算重新计算。
   */
  function checkNow(id?: string): void {
    const target = id ?? taskId ?? lastTaskId ?? pausedTaskId
    if (!target) return
    start(target)
  }

  /** 切后台：停止定时器并保留现场；回前台由 listener 立即回查。 */
  function handleVisibilityChange(): void {
    if (typeof document === 'undefined') return
    if (document.hidden) {
      if (running && taskId) {
        pausedTaskId = taskId
        stopInternal()
        state.value = { ...state.value, nextDelayMs: null }
      }
      return
    }
    if (pausedTaskId) {
      const resumeId = pausedTaskId
      pausedTaskId = null
      start(resumeId)
    }
  }

  const listeners = new Set<() => void>()
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityChange)
    listeners.add(() => document.removeEventListener('visibilitychange', handleVisibilityChange))
  }

  /** 页面离开/组件卸载时调用：停止轮询并移除全部监听。 */
  function dispose(): void {
    pausedTaskId = null
    stop()
    for (const remove of listeners) remove()
    listeners.clear()
  }

  /**
   * 采纳一份由页面动作（如主动取消）拿到的服务端快照。
   *
   * 只做两件事：停止自动回查、把服务端返回的快照原样放进 state。
   * 终态由服务端的 `terminal` 决定，前端不改写状态、不虚构原因；
   * 非终态快照会保留 `polling` 语义之外的 idle 态，交由页面决定是否再回查。
   */
  function adopt(snapshot: VisionTaskStatusSnapshot): void {
    pausedTaskId = null
    stopInternal()
    lastTaskId = snapshot.taskId
    state.value = {
      phase: snapshot.terminal ? 'terminal' : 'idle',
      snapshot,
      attempts: state.value.attempts,
      nextDelayMs: null,
      lastCheckedAt: now().toISOString(),
      lastError: null,
    }
  }

  return { state, start, stop, checkNow, adopt, dispose }
}

/** 把服务端状态映射为中文标签；未知状态原样展示，不猜测。 */
export function visionTaskStatusLabel(status: string): string {
  switch (status) {
    case 'queued': return '排队中'
    case 'running': return '处理中'
    case 'succeeded': return '已完成'
    case 'failed': return '失败'
    case 'cancelled': return '已取消'
    case 'timeout': return '超时'
    default: return `未知状态（${status}）`
  }
}
