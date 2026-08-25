import { normalizeVoiceText } from './recognition'

/**
 * 严格白名单语音指令。只覆盖确认发送、取消、重读上一条、停止朗读、重说/继续说。
 * 不解析开放域意图，避免被当成“能做事的助手”。
 */
export type VoiceCommandId =
  | 'confirm_send'
  | 'cancel_send'
  | 'repeat_answer'
  | 'stop_speaking'
  | 'redo_dictation'
  | 'resume_dictation'

const COMMAND_PATTERNS: ReadonlyArray<{ id: VoiceCommandId; patterns: RegExp[] }> = [
  {
    id: 'confirm_send',
    patterns: [
      /^(请)?(确认)?发送(吧|吧。|。)?$/,
      /^发送$/,
      /^发出(去|吧)?$/,
      /^确认发送$/,
      /^好了发送$/,
    ],
  },
  {
    id: 'cancel_send',
    patterns: [
      /^(取消|不要发送|先不发|不发了|算了)(吧)?$/,
    ],
  },
  {
    id: 'repeat_answer',
    patterns: [
      /^(上一条)?(再[说读]一遍|重复(一下|回答|朗读)?|再读一次|再听一遍)(回答|上一条)?$/,
      /^把上一条再[说读]一遍$/,
      /^再朗读$/,
    ],
  },
  {
    id: 'stop_speaking',
    patterns: [
      /^(停止朗读|别读了|不要读了|安静|停)$/,
    ],
  },
  {
    id: 'redo_dictation',
    patterns: [
      /^(重说|重新说|再说一遍问题|重说一遍|我重说)$/,
    ],
  },
  {
    id: 'resume_dictation',
    patterns: [
      /^(继续说|接着说|我还有)$/,
    ],
  },
]

/** 匹配白名单指令；无法识别则返回 null（忽略，不执行开放意图）。 */
export function matchVoiceCommand(text: string): VoiceCommandId | null {
  const compact = normalizeVoiceText(text)
  if (!compact) return null
  // 也保留轻度标点后的整句匹配
  const soft = text.normalize('NFKC').trim().replace(/[。！？.!?]+$/g, '')
  for (const entry of COMMAND_PATTERNS) {
    for (const pattern of entry.patterns) {
      if (pattern.test(compact) || pattern.test(soft) || pattern.test(text.trim())) {
        return entry.id
      }
    }
  }
  return null
}

export const VOICE_COMMAND_HINT =
  '可说：发送吧（需说两遍确认）、取消、上一条再说一遍、停止朗读、重说、继续说'

const DEFAULT_CONFIRM_WINDOW_MS = 5000

/** 语音发送二次确认门闩：第一次只提示，第二次才真正发送。 */
export function createSendConfirmGate(options: {
  windowMs?: number
  onPrompt?: () => void
  onConfirmed?: () => void
  onCancelled?: () => void
  onExpired?: () => void
} = {}) {
  let pending = false
  let timer: ReturnType<typeof setTimeout> | null = null
  const windowMs = options.windowMs ?? DEFAULT_CONFIRM_WINDOW_MS

  function clearTimer(): void {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function arm(): void {
    clearTimer()
    timer = setTimeout(() => {
      timer = null
      pending = false
      options.onExpired?.()
    }, windowMs)
  }

  return {
    isPending: () => pending,
    handleSendIntent(): 'prompt' | 'confirmed' {
      if (!pending) {
        pending = true
        arm()
        options.onPrompt?.()
        return 'prompt'
      }
      pending = false
      clearTimer()
      options.onConfirmed?.()
      return 'confirmed'
    },
    cancel(): void {
      const wasPending = pending
      pending = false
      clearTimer()
      if (wasPending) options.onCancelled?.()
    },
    reset(): void {
      pending = false
      clearTimer()
    },
  }
}
