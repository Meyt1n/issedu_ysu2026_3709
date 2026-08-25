export interface SpeechRecognitionAlternativeLike {
  transcript: string
}

export interface SpeechRecognitionResultLike {
  isFinal: boolean
  length: number
  [index: number]: SpeechRecognitionAlternativeLike
}

export interface SpeechRecognitionResultListLike {
  length: number
  [index: number]: SpeechRecognitionResultLike
}

export interface SpeechRecognitionEventLike extends Event {
  resultIndex: number
  results: SpeechRecognitionResultListLike
}

export interface SpeechRecognitionErrorEventLike extends Event {
  error?: string
}

export interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  onstart: (() => void) | null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

export interface SpeechRecognitionOptions {
  continuous?: boolean
  interimResults?: boolean
  maxAlternatives?: number
}

interface SpeechWindow extends Window {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

function speechWindow(): SpeechWindow | null {
  return typeof window === 'undefined' ? null : (window as SpeechWindow)
}

export function isSpeechInputSupported(): boolean {
  const currentWindow = speechWindow()
  return Boolean(currentWindow?.SpeechRecognition || currentWindow?.webkitSpeechRecognition)
}

export function isSpeechOutputSupported(): boolean {
  const currentWindow = speechWindow()
  return Boolean(currentWindow?.speechSynthesis && typeof SpeechSynthesisUtterance !== 'undefined')
}

/** 识别会话结束后的快速重启间隔。 */
export const VOICE_RESTART_DELAY_MS = 30

/** 听写态静音多久视为说完（停麦，保留草稿待发送）。 */
export const DICTATION_SILENCE_MS = 1600

/** 默认唤醒词：连呼两声名字即可。 */
export const DEFAULT_WAKE_PHRASE = '小燕小燕'

export function createSpeechRecognition(
  lang = 'zh-CN',
  options: SpeechRecognitionOptions = {},
): SpeechRecognitionLike | null {
  const currentWindow = speechWindow()
  const Constructor = currentWindow?.SpeechRecognition ?? currentWindow?.webkitSpeechRecognition
  if (!Constructor) return null

  const recognition = new Constructor()
  recognition.lang = lang
  recognition.continuous = options.continuous ?? false
  recognition.interimResults = options.interimResults ?? true
  recognition.maxAlternatives = options.maxAlternatives ?? 3
  return recognition
}

function alternativeConfidence(alternative: SpeechRecognitionAlternativeLike): number {
  const confidence = (alternative as { confidence?: number }).confidence
  return typeof confidence === 'number' && Number.isFinite(confidence) ? confidence : -1
}

function chineseDensity(text: string): number {
  const chars = [...text]
  if (chars.length === 0) return 0
  const chinese = chars.filter((char) => /[\u4e00-\u9fff]/.test(char)).length
  return chinese / chars.length
}

export function pickBestAlternative(result: SpeechRecognitionResultLike): string {
  let best = ''
  let bestConfidence = -2
  let bestDensity = -1
  for (let index = 0; index < result.length; index += 1) {
    const transcript = result[index]?.transcript?.trim() ?? ''
    if (!transcript) continue
    const confidence = alternativeConfidence(result[index]!)
    const density = chineseDensity(transcript)
    if (
      confidence > bestConfidence ||
      (confidence === bestConfidence && density > bestDensity) ||
      (confidence === bestConfidence && density === bestDensity && transcript.length > best.length)
    ) {
      best = transcript
      bestConfidence = confidence
      bestDensity = density
    }
  }
  return best
}

function joinTranscriptParts(parts: string[]): string {
  if (parts.length === 0) return ''
  let combined = parts[0]!
  for (let index = 1; index < parts.length; index += 1) {
    const next = parts[index]!
    const left = combined.slice(-1)
    const right = next.slice(0, 1)
    const needSpace = !/[\u4e00-\u9fff]/.test(left) || !/[\u4e00-\u9fff]/.test(right)
    combined += needSpace ? ` ${next}` : next
  }
  return combined
}

export function transcriptFromEvent(event: SpeechRecognitionEventLike): string {
  const parts: string[] = []
  for (let index = 0; index < event.results.length; index += 1) {
    const transcript = pickBestAlternative(event.results[index]!)
    if (transcript) parts.push(transcript)
  }
  return joinTranscriptParts(parts)
}

export function latestTranscriptFromEvent(event: SpeechRecognitionEventLike): string {
  const parts: string[] = []
  const start = Math.max(0, Math.min(event.resultIndex, event.results.length))
  for (let index = start; index < event.results.length; index += 1) {
    const transcript = pickBestAlternative(event.results[index]!)
    if (transcript) parts.push(transcript)
  }
  return joinTranscriptParts(parts) || transcriptFromEvent(event)
}

const WAKE_ASR_CORRECTIONS: ReadonlyArray<readonly [RegExp, string]> = [
  [/晓燕|小严|小研|小嫣|小延|小言|小烟/g, '小燕'],
  [/小燕啊小燕|小燕呀小燕|小燕呢小燕|嘿小燕小燕|喂小燕小燕/g, '小燕小燕'],
]

export function normalizeVoiceText(text: string): string {
  let normalized = text.normalize('NFKC').toLocaleLowerCase()
  for (const [pattern, replacement] of WAKE_ASR_CORRECTIONS) {
    normalized = normalized.replace(pattern, replacement)
  }
  return normalized.replace(/[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]/g, '')
}

function wakePhrasePattern(phrase: string): RegExp | null {
  const normalizedPhrase = phrase.normalize('NFKC').trim()
  if (!normalizedPhrase) return null
  const chars = [...normalizedPhrase]
    .map((char) => char.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('[\\s，。！？；：、,.!?;:\'"“”‘’（）()[\\]{}<>《》]*')
  return new RegExp(chars, 'iu')
}

export function containsWakePhrase(text: string, phrase = DEFAULT_WAKE_PHRASE): boolean {
  const pattern = wakePhrasePattern(phrase)
  if (!pattern) return false
  if (pattern.test(text)) return true
  return pattern.test(normalizeVoiceText(text))
}

export function transcriptAfterWakePhrase(text: string, phrase = DEFAULT_WAKE_PHRASE): string {
  const pattern = wakePhrasePattern(phrase)
  if (!pattern) return text.trim()
  const direct = pattern.exec(text)
  if (direct && direct.index !== undefined) {
    return text
      .slice(direct.index + direct[0].length)
      .replace(/^[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]+/, '')
      .trim()
  }

  const normalized = normalizeVoiceText(text)
  const normalizedPattern = wakePhrasePattern(normalizeVoiceText(phrase))
  const normalizedMatch = normalizedPattern?.exec(normalized)
  if (!normalizedMatch || normalizedMatch.index === undefined) return ''
  const trailingNormalized = normalized.slice(normalizedMatch.index + normalizedMatch[0].length)
  if (!trailingNormalized) return ''
  const rawCompact = text.replace(/[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]/g, '')
  return rawCompact.slice(Math.max(0, rawCompact.length - trailingNormalized.length)).trim()
}

/** 查询麦克风权限；不支持 Permissions API 时返回 null。 */
export async function queryMicrophonePermission(): Promise<'granted' | 'denied' | 'prompt' | null> {
  try {
    const permissions = navigator.permissions
    if (!permissions?.query) return null
    const status = await permissions.query({ name: 'microphone' as PermissionName })
    if (status.state === 'granted' || status.state === 'denied' || status.state === 'prompt') {
      return status.state
    }
    return null
  } catch {
    return null
  }
}
