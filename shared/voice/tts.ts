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

export const SPEECH_DEFAULTS = { rate: 0.92, pitch: 1.05, volume: 1 } as const

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
  return segments.filter((segment) => segment.length > 0)
}

export function prepareSpeechText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[*_`~#]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

const NATURAL_VOICE_PATTERN =
  /natural|neural|premium|enhanced|online|xiaoxiao|xiaoyi|yunxi|yunjian|yunyang|yunxia|xiaochen|xiaomo|xiaoxuan|tingting|ting-ting|meijia|mei-jia|晓晓|晓伊|云希|云健|云扬|云夏|婷婷/i
const ROBOTIC_VOICE_PATTERN = /espeak|eloquence|compact|novelty|whisper|robot|mono/i
const PLAIN_LOCAL_VOICE_PATTERN =
  /microsoft huihui|microsoft yaoyao|microsoft kangkang|\bhuihui\b|\byaoyao\b|\bkangkang\b|chinese \(simplified\)|chinese, simplified/i

function chineseVoiceScore(voice: SpeechVoiceLike): number {
  const lang = voice.lang.toLowerCase().replace('_', '-')
  if (!lang.startsWith('zh')) return -1
  let score = lang.startsWith('zh-cn') || lang === 'zh' ? 100 : 50
  const name = voice.name
  if (NATURAL_VOICE_PATTERN.test(name)) score += 70
  if (voice.localService) score += 15
  if (PLAIN_LOCAL_VOICE_PATTERN.test(name) && !NATURAL_VOICE_PATTERN.test(name)) score -= 25
  if (ROBOTIC_VOICE_PATTERN.test(name)) score -= 60
  if (voice.default) score += 5
  return score
}

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

function speechWindow(): Window | null {
  return typeof window === 'undefined' ? null : window
}

function getVoicesSafe(synth: SpeechSynthesisLike): SpeechVoiceLike[] {
  try {
    return synth.getVoices?.() ?? []
  } catch {
    return []
  }
}

export function waitForVoices(synth: SpeechSynthesisLike, timeoutMs = 800): Promise<SpeechVoiceLike[]> {
  const immediate = getVoicesSafe(synth)
  if (immediate.length > 0 || typeof synth.addEventListener !== 'function') {
    return Promise.resolve(immediate)
  }
  return new Promise((resolve) => {
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

export interface SpeakProgress {
  index: number
  total: number
  segment: string
}

export interface SpeakOptions {
  onFinished?: () => void
  onProgress?: (progress: SpeakProgress) => void
}

let speechToken = 0
let activeSegments: string[] = []
let activeIndex = 0
let activeSynth: SpeechSynthesisLike | null = null
let activeVoice: SpeechVoiceLike | null = null
let activeFinish: (() => void) | null = null
let activeOnProgress: ((progress: SpeakProgress) => void) | null = null

export function stopSpeaking(): void {
  speechToken += 1
  activeSegments = []
  activeIndex = 0
  activeFinish = null
  activeOnProgress = null
  activeSynth = null
  activeVoice = null
  speechWindow()?.speechSynthesis?.cancel()
}

/** 跳过当前句，继续下一段；已是最后一段则结束。 */
export function skipSpeakingSegment(): boolean {
  if (!activeSynth || activeSegments.length === 0) return false
  const token = speechToken
  speechWindow()?.speechSynthesis?.cancel()
  const nextIndex = activeIndex + 1
  if (nextIndex >= activeSegments.length) {
    const finish = activeFinish
    stopSpeaking()
    finish?.()
    return true
  }
  speakSegments(activeSynth, activeSegments, activeVoice, token, activeFinish ?? (() => undefined), nextIndex, activeOnProgress)
  return true
}

/** 从指定句开始重读（含当前句）；越界则忽略。 */
export function jumpSpeakingSegment(index: number): boolean {
  if (!activeSynth || activeSegments.length === 0) return false
  if (index < 0 || index >= activeSegments.length) return false
  const token = speechToken
  speechWindow()?.speechSynthesis?.cancel()
  speakSegments(activeSynth, activeSegments, activeVoice, token, activeFinish ?? (() => undefined), index, activeOnProgress)
  return true
}

export function getSpeakingSegments(): readonly string[] {
  return activeSegments
}

export function getSpeakingIndex(): number {
  return activeIndex
}

function speakSegments(
  synth: SpeechSynthesisLike,
  segments: string[],
  voice: SpeechVoiceLike | null,
  token: number,
  finish: () => void,
  index = 0,
  onProgress: ((progress: SpeakProgress) => void) | null = null,
): void {
  if (token !== speechToken) return
  activeSynth = synth
  activeSegments = segments
  activeVoice = voice
  activeFinish = finish
  activeOnProgress = onProgress
  activeIndex = index
  const segment = segments[index]
  if (!segment) {
    finish()
    return
  }
  onProgress?.({ index, total: segments.length, segment })
  const utterance = new SpeechSynthesisUtterance(segment)
  utterance.lang = voice?.lang ?? 'zh-CN'
  if (voice) utterance.voice = voice as SpeechSynthesisVoice
  utterance.rate = SPEECH_DEFAULTS.rate
  utterance.pitch = SPEECH_DEFAULTS.pitch
  utterance.volume = SPEECH_DEFAULTS.volume
  utterance.onend = () => {
    if (token !== speechToken) return
    if (index + 1 < segments.length) {
      speakSegments(synth, segments, voice, token, finish, index + 1, onProgress)
    } else {
      finish()
    }
  }
  utterance.onerror = () => {
    if (token !== speechToken) return
    finish()
  }
  synth.speak(utterance)
}

export function speakText(text: string, onFinishedOrOptions?: (() => void) | SpeakOptions): boolean {
  const options: SpeakOptions = typeof onFinishedOrOptions === 'function'
    ? { onFinished: onFinishedOrOptions }
    : (onFinishedOrOptions ?? {})
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
    if (token === speechToken) {
      activeSegments = []
      activeIndex = 0
      activeSynth = null
      activeVoice = null
      activeFinish = null
      activeOnProgress = null
    }
    options.onFinished?.()
  }

  const loadedVoices = getVoicesSafe(synth)
  if (loadedVoices.length > 0 || typeof synth.addEventListener !== 'function') {
    speakSegments(synth, segments, pickPreferredChineseVoice(loadedVoices), token, finish, 0, options.onProgress ?? null)
  } else {
    void waitForVoices(synth).then((voices) => {
      if (token !== speechToken) return
      speakSegments(synth, segments, pickPreferredChineseVoice(voices), token, finish, 0, options.onProgress ?? null)
    })
  }
  return true
}
