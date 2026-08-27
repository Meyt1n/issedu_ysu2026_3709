import { normalizeVoiceText } from './recognition'

/**
 * 严格白名单语音指令。只覆盖立即发送、取消自动发送、重读上一条、停止朗读、重说/继续说。
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
      /^现在发送$/,
    ],
  },
  {
    id: 'cancel_send',
    patterns: [
      /^(取消|不要发送|先不发|不发了|算了|等等)(吧)?$/,
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

/**
 * 白名单指令的完整口语形态（规范化后），用于判断「还在说指令的前半句」。
 * 与 COMMAND_PATTERNS 保持同源语料；只做前缀判断，不解析开放域意图。
 */
const COMMAND_PHRASES: readonly string[] = [
  '发送', '发送吧', '请发送', '请确认发送吧', '确认发送', '发出去', '发出吧', '好了发送', '现在发送',
  '取消', '取消吧', '不要发送', '先不发', '不发了', '算了', '等等',
  '再说一遍', '再读一遍', '重复', '重复一下', '重复回答', '重复朗读', '再读一次', '再听一遍',
  '上一条再说一遍', '上一条再读一遍', '把上一条再说一遍', '再朗读',
  '停止朗读', '别读了', '不要读了', '安静', '停',
  '重说', '重新说', '再说一遍问题', '重说一遍', '我重说',
  '继续说', '接着说', '我还有',
]

/**
 * 判断文本是否可能是白名单指令的未说完前缀（如「上一条再说」）。
 * 用于指令聆听期：可能是指令就再等等，否则应把这段话累加回口述草稿，避免丢字。
 */
export function couldBeVoiceCommandPrefix(text: string): boolean {
  const compact = normalizeVoiceText(text)
  if (!compact) return false
  return COMMAND_PHRASES.some((phrase) => phrase.startsWith(compact))
}

/** 匹配白名单指令；无法识别则返回 null（忽略，不执行开放意图）。 */
export function matchVoiceCommand(text: string): VoiceCommandId | null {
  const compact = normalizeVoiceText(text)
  if (!compact) return null
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
  '说完后会倒计时自动发送；可说取消、继续说、发送吧（立即发送）、上一条再说一遍、停止朗读、重说'

/** 听写结束后无新输入时，等待若干秒再自动发送。 */
export const DEFAULT_AUTO_SEND_DELAY_MS = 3000

/**
 * 无输入等待自动发送：
 * - start(draft)：开始倒计时
 * - 倒计时结束且草稿仍非空 → onAutoSend
 * - cancel / reset：中止
 * - 期间说「发送吧」可由页面直接 send，并 reset
 */
export function createAutoSendScheduler(options: {
  delayMs?: number
  onTick?: (remainMs: number) => void
  onAutoSend?: (draft: string) => void
  onCancelled?: () => void
  onArmed?: (delayMs: number, draft: string) => void
} = {}) {
  let timer: ReturnType<typeof setTimeout> | null = null
  let tickTimer: ReturnType<typeof setInterval> | null = null
  let pendingDraft = ''
  let deadline = 0

  function clearTimers(): void {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    if (tickTimer) {
      clearInterval(tickTimer)
      tickTimer = null
    }
  }

  function remainMs(): number {
    if (!timer) return 0
    return Math.max(0, deadline - Date.now())
  }

  return {
    isPending: () => timer !== null,
    remainMs,
    start(draft: string, delayMs = options.delayMs ?? DEFAULT_AUTO_SEND_DELAY_MS): boolean {
      const content = draft.trim()
      if (!content) return false
      clearTimers()
      pendingDraft = content
      const wait = Math.max(1000, Math.min(delayMs, 10_000))
      deadline = Date.now() + wait
      options.onArmed?.(wait, content)
      options.onTick?.(wait)
      tickTimer = setInterval(() => {
        const left = remainMs()
        options.onTick?.(left)
        if (left <= 0 && tickTimer) {
          clearInterval(tickTimer)
          tickTimer = null
        }
      }, 250)
      timer = setTimeout(() => {
        timer = null
        if (tickTimer) {
          clearInterval(tickTimer)
          tickTimer = null
        }
        const toSend = pendingDraft.trim()
        pendingDraft = ''
        if (toSend) options.onAutoSend?.(toSend)
      }, wait)
      return true
    },
    cancel(): void {
      const wasPending = timer !== null
      clearTimers()
      pendingDraft = ''
      deadline = 0
      if (wasPending) options.onCancelled?.()
    },
    reset(): void {
      clearTimers()
      pendingDraft = ''
      deadline = 0
    },
  }
}

/** @deprecated 已改为倒计时自动发送，请用 createAutoSendScheduler。 */
export function createSendConfirmGate(
  _options: Record<string, unknown> = {},
): ReturnType<typeof createAutoSendScheduler> {
  return createAutoSendScheduler()
}
