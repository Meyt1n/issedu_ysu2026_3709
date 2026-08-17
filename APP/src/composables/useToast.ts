import { reactive, readonly } from 'vue'

export type ToastTone = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  text: string
  tone: ToastTone
}

const DEFAULT_DURATION = 2800

const state = reactive<{ items: ToastItem[] }>({ items: [] })
let nextId = 1
const timers = new Map<number, ReturnType<typeof setTimeout>>()

export function dismissToast(id: number): void {
  const timer = timers.get(id)
  if (timer) {
    clearTimeout(timer)
    timers.delete(id)
  }
  const index = state.items.findIndex(item => item.id === id)
  if (index >= 0) state.items.splice(index, 1)
}

/** 顶部弹出一条轻提示；同屏最多 3 条，超出先移除最旧。 */
export function showToast(text: string, tone: ToastTone = 'success', duration = DEFAULT_DURATION): number {
  const id = nextId++
  state.items.push({ id, text, tone })
  while (state.items.length > 3) dismissToast(state.items[0]!.id)
  timers.set(
    id,
    setTimeout(() => dismissToast(id), duration),
  )
  return id
}

/** 测试辅助：清空全部提示与定时器。 */
export function clearToasts(): void {
  for (const item of [...state.items]) dismissToast(item.id)
}

export function useToasts() {
  return { toasts: readonly(state).items }
}
