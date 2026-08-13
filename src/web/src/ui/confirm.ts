import { reactive, readonly } from 'vue'

export interface ConfirmOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  tone?: 'danger' | 'primary'
}

interface ConfirmState {
  open: boolean
  options: Required<ConfirmOptions>
}

const DEFAULTS: Required<ConfirmOptions> = {
  title: '',
  message: '',
  confirmText: '确认',
  cancelText: '再想想',
  tone: 'danger',
}

const state = reactive<ConfirmState>({
  open: false,
  options: { ...DEFAULTS },
})

let pendingResolve: ((value: boolean) => void) | null = null

export const confirmState = readonly(state)

/** 打开确认弹窗；返回用户的选择。同一时间只允许一个确认请求。 */
export function askConfirm(options: ConfirmOptions): Promise<boolean> {
  if (pendingResolve) pendingResolve(false)
  state.options = { ...DEFAULTS, ...options }
  state.open = true
  return new Promise<boolean>(resolve => {
    pendingResolve = resolve
  })
}

export function settleConfirm(accepted: boolean): void {
  state.open = false
  pendingResolve?.(accepted)
  pendingResolve = null
}
