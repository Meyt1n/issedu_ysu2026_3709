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
  recognition.maxAlternatives = options.maxAlternatives ?? 1
  return recognition
}

/** Combine the current recognition result list into the input draft text. */
export function transcriptFromEvent(event: SpeechRecognitionEventLike): string {
  const parts: string[] = []
  for (let index = 0; index < event.results.length; index += 1) {
    const transcript = event.results[index]?.[0]?.transcript
    if (typeof transcript === 'string' && transcript.trim()) parts.push(transcript.trim())
  }
  return parts.join(' ')
}

/** Normalize only for wake-phrase matching; the original transcript stays untouched. */
export function normalizeVoiceText(text: string): string {
  return text
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(/[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]/g, '')
}

function wakePhrasePattern(phrase: string): RegExp | null {
  const normalizedPhrase = phrase.normalize('NFKC').trim()
  if (!normalizedPhrase) return null
  const chars = [...normalizedPhrase]
    .map(char => char.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('[\\s，。！？；：、,.!?;:\'"“”‘’（）()[\\]{}<>《》]*')
  return new RegExp(chars, 'iu')
}

/** Match "小燕打开" while tolerating punctuation inserted by browser ASR. */
export function containsWakePhrase(text: string, phrase = '小燕打开'): boolean {
  const pattern = wakePhrasePattern(phrase)
  return Boolean(pattern?.test(text))
}

/** Remove the wake phrase and return the spoken content that follows it. */
export function transcriptAfterWakePhrase(text: string, phrase = '小燕打开'): string {
  const pattern = wakePhrasePattern(phrase)
  if (!pattern) return text.trim()
  const match = pattern.exec(text)
  if (!match || match.index === undefined) return ''
  return text
    .slice(match.index + match[0].length)
    .replace(/^[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]+/, '')
    .trim()
}

export function isSpeechOutputSupported(): boolean {
  const currentWindow = speechWindow()
  return Boolean(currentWindow?.speechSynthesis && typeof SpeechSynthesisUtterance !== 'undefined')
}

export interface SpeechVoiceLike {
  name: string
  lang: string
  localService: boolean
  default: boolean
}

export interface SpeechSynthesisLike {
  cancel: () => void
  speak: (utterance: SpeechSynthesisUtterance) => void
  getVoices?: () => SpeechVoiceLike[]
  addEventListener?: (type: 'voiceschanged', listener: () => void) => void
  removeEventListener?: (type: 'voiceschanged', listener: () => void) => void
}

/** 适老可读的默认播报参数：语速略慢，音高与音量保持自然。 */
export const SPEECH_DEFAULTS = { rate: 0.95, pitch: 1, volume: 1 } as const

/**
 * 长文本按句切分：规避部分浏览器长 utterance 中途静音的问题，
 * 也让“停止朗读”响应更及时。
 */
export function splitSpeechSegments(text: string, maxLength = 120): string[] {
  const content = text.trim()
  if (!content) return []
  if (content.length <= maxLength) return [content]

  const sentences = content.match(/[^。！？!?\n]+[。！？!?\n]*/g) ?? [content]
  const segments: string[] = []
  let current = ''
  const flush = () => {
    if (current.trim()) segments.push(current.trim())
    current = ''
  }
  for (const sentence of sentences) {
    if (sentence.length > maxLength) {
      flush()
      // 单句仍超长时退化为按次级标点/定长切分。
      const clauses = sentence.match(/[^，、；：,;:]+[，、；：,;:]*/g) ?? [sentence]
      for (const clause of clauses) {
        if (clause.length > maxLength) {
          flush()
          for (let index = 0; index < clause.length; index += maxLength) {
            segments.push(clause.slice(index, index + maxLength).trim())
          }
          continue
        }
        if (current.length + clause.length > maxLength) flush()
        current += clause
      }
      flush()
      continue
    }
    if (current.length + sentence.length > maxLength) flush()
    current += sentence
  }
  flush()
  return segments.filter(segment => segment.length > 0)
}

/** 去掉 Markdown 装饰符号并压缩空白，避免朗读读出“星号井号”。 */
export function prepareSpeechText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[*_`~#]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

const NATURAL_VOICE_PATTERN = /natural|neural|premium|enhanced|xiaoxiao|xiaoyi|yunxi|yunjian|yunyang|tingting|ting-ting|meijia|mei-jia|晓|云|婷/i
const ROBOTIC_VOICE_PATTERN = /espeak|eloquence|compact|novelty|whisper/i

function chineseVoiceScore(voice: SpeechVoiceLike): number {
  const lang = voice.lang.toLowerCase().replace('_', '-')
  if (!lang.startsWith('zh')) return -1
  let score = lang.startsWith('zh-cn') || lang === 'zh' ? 100 : 50
  // 本地语音优先：合成不出网，符合“健康数据默认不出网”的产品承诺。
  if (voice.localService) score += 40
  if (NATURAL_VOICE_PATTERN.test(voice.name)) score += 25
  if (ROBOTIC_VOICE_PATTERN.test(voice.name)) score -= 60
  if (voice.default) score += 5
  return score
}

/**
 * 在浏览器已加载的语音里挑一条更自然的中文音色：
 * 普通话 zh-CN 优先，其次其他中文；本地语音优先于联网语音；
 * “Natural/晓晓/婷婷”等高质量命名加分，明显机械的引擎降权。
 * 没有任何中文语音时返回 null，由调用方退回 lang 兜底。
 */
export function pickPreferredChineseVoice<T extends SpeechVoiceLike>(voices: readonly T[]): T | null {
  let best: T | null = null
  let bestScore = -1
  for (const voice of voices) {
    const score = chineseVoiceScore(voice)
    if (score > bestScore) {
      best = voice
      bestScore = score
    }
  }
  return bestScore >= 0 ? best : null
}

function getVoicesSafe(synth: SpeechSynthesisLike): SpeechVoiceLike[] {
  try {
    return synth.getVoices?.() ?? []
  } catch {
    return []
  }
}

/** voices 延迟加载时等待一次 voiceschanged，超时后返回当前列表（可能为空）。 */
export function waitForVoices(synth: SpeechSynthesisLike, timeoutMs = 1500): Promise<SpeechVoiceLike[]> {
  const immediate = getVoicesSafe(synth)
  if (immediate.length > 0 || typeof synth.addEventListener !== 'function') {
    return Promise.resolve(immediate)
  }
  return new Promise(resolve => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      synth.removeEventListener?.('voiceschanged', finish)
      resolve(getVoicesSafe(synth))
    }
    const timer = setTimeout(finish, timeoutMs)
    synth.addEventListener?.('voiceschanged', finish)
  })
}

/** 递增令牌：stopSpeaking 或新播报后，旧播报链上任何延迟回调都会失效。 */
let speechToken = 0

export function stopSpeaking(): void {
  speechToken += 1
  const currentWindow = speechWindow()
  currentWindow?.speechSynthesis?.cancel()
}

function speakSegments(
  synth: SpeechSynthesisLike,
  segments: string[],
  voice: SpeechVoiceLike | null,
  token: number,
  finish: () => void,
  index = 0,
): void {
  if (token !== speechToken) return
  const segment = segments[index]
  if (!segment) {
    finish()
    return
  }
  const utterance = new SpeechSynthesisUtterance(segment)
  utterance.lang = voice?.lang ?? 'zh-CN'
  if (voice) utterance.voice = voice as SpeechSynthesisVoice
  utterance.rate = SPEECH_DEFAULTS.rate
  utterance.pitch = SPEECH_DEFAULTS.pitch
  utterance.volume = SPEECH_DEFAULTS.volume
  utterance.onend = () => {
    if (token !== speechToken) return
    if (index + 1 < segments.length) speakSegments(synth, segments, voice, token, finish, index + 1)
    else finish()
  }
  utterance.onerror = () => {
    // 被 stopSpeaking/新播报打断时不再回调；真实错误走文字降级。
    if (token !== speechToken) return
    finish()
  }
  synth.speak(utterance)
}

/** Speak only after an explicit user action; no audio is sent to the API. */
export function speakText(text: string, onFinished?: () => void): boolean {
  const currentWindow = speechWindow()
  const synth = currentWindow?.speechSynthesis as SpeechSynthesisLike | undefined
  if (!synth || typeof SpeechSynthesisUtterance === 'undefined') return false
  const content = prepareSpeechText(text)
  if (!content) return false

  speechToken += 1
  const token = speechToken
  synth.cancel()

  const segments = splitSpeechSegments(content)
  let finished = false
  const finish = () => {
    if (finished) return
    finished = true
    onFinished?.()
  }

  const loadedVoices = getVoicesSafe(synth)
  if (loadedVoices.length > 0 || typeof synth.addEventListener !== 'function') {
    speakSegments(synth, segments, pickPreferredChineseVoice(loadedVoices), token, finish)
  } else {
    void waitForVoices(synth).then(voices => {
      if (token !== speechToken) return
      speakSegments(synth, segments, pickPreferredChineseVoice(voices), token, finish)
    })
  }
  return true
}
