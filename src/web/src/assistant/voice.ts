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
  // 多候选便于挑选更稳的中文结果，降低同音误识。
  recognition.maxAlternatives = options.maxAlternatives ?? 3
  return recognition
}

/** 识别会话结束后的快速重启间隔：压低唤醒空窗，同时避免浏览器连启报错。 */
export const VOICE_RESTART_DELAY_MS = 30

function alternativeConfidence(alternative: SpeechRecognitionAlternativeLike): number {
  const confidence = (alternative as { confidence?: number }).confidence
  return typeof confidence === 'number' && Number.isFinite(confidence) ? confidence : -1
}

function chineseDensity(text: string): number {
  const chars = [...text]
  if (chars.length === 0) return 0
  const chinese = chars.filter(char => /[\u4e00-\u9fff]/.test(char)).length
  return chinese / chars.length
}

/** 在单个识别结果的多个候选中选更稳的一条：置信度优先，其次中文密度。 */
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
    // 中文片段之间不加空格，减少草稿里无意义空隙。
    const needSpace = !/[\u4e00-\u9fff]/.test(left) || !/[\u4e00-\u9fff]/.test(right)
    combined += needSpace ? ` ${next}` : next
  }
  return combined
}

/** Combine the current recognition result list into the input draft text. */
export function transcriptFromEvent(event: SpeechRecognitionEventLike): string {
  const parts: string[] = []
  for (let index = 0; index < event.results.length; index += 1) {
    const transcript = pickBestAlternative(event.results[index]!)
    if (transcript) parts.push(transcript)
  }
  return joinTranscriptParts(parts)
}

/**
 * 只取 resultIndex 起的最新片段：唤醒判定优先看最近 interim，
 * 避免整段历史缓冲拖慢“小燕打开”切换。
 */
export function latestTranscriptFromEvent(event: SpeechRecognitionEventLike): string {
  const parts: string[] = []
  const start = Math.max(0, Math.min(event.resultIndex, event.results.length))
  for (let index = start; index < event.results.length; index += 1) {
    const transcript = pickBestAlternative(event.results[index]!)
    if (transcript) parts.push(transcript)
  }
  return joinTranscriptParts(parts) || transcriptFromEvent(event)
}

/** ASR 常见同音/近音纠偏，仅用于唤醒匹配，不改写入草稿的原文。 */
const WAKE_ASR_CORRECTIONS: ReadonlyArray<readonly [RegExp, string]> = [
  [/晓燕|小严|小研|小嫣|小延|小言|小烟/g, '小燕'],
  [/打开开|打开下|打开一下|打开助手|打开家健镜/g, '打开'],
]

/** Normalize only for wake-phrase matching; the original transcript stays untouched. */
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
    .map(char => char.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('[\\s，。！？；：、,.!?;:\'"“”‘’（）()[\\]{}<>《》]*')
  return new RegExp(chars, 'iu')
}

/** Match "小燕打开" while tolerating punctuation and common ASR near-homophones. */
export function containsWakePhrase(text: string, phrase = '小燕打开'): boolean {
  const pattern = wakePhrasePattern(phrase)
  if (!pattern) return false
  if (pattern.test(text)) return true
  // 归一化后再匹配一次，覆盖“小严打开 / 晓燕，打开助手”等误识。
  return pattern.test(normalizeVoiceText(text))
}

/** Remove the wake phrase and return the spoken content that follows it. */
export function transcriptAfterWakePhrase(text: string, phrase = '小燕打开'): string {
  const pattern = wakePhrasePattern(phrase)
  if (!pattern) return text.trim()
  const direct = pattern.exec(text)
  if (direct && direct.index !== undefined) {
    return text
      .slice(direct.index + direct[0].length)
      .replace(/^[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]+/, '')
      .trim()
  }

  // 原文未直接命中时，按归一化位置估算后缀长度，尽量保留用户后续提问。
  const normalized = normalizeVoiceText(text)
  const normalizedPattern = wakePhrasePattern(normalizeVoiceText(phrase))
  const normalizedMatch = normalizedPattern?.exec(normalized)
  if (!normalizedMatch || normalizedMatch.index === undefined) return ''
  const trailingNormalized = normalized.slice(normalizedMatch.index + normalizedMatch[0].length)
  if (!trailingNormalized) return ''
  const rawCompact = text.replace(/[\s，。！？；：、,.!?;:'"“”‘’（）()[\]{}<>《》]/g, '')
  const trailingRaw = rawCompact.slice(Math.max(0, rawCompact.length - trailingNormalized.length))
  return trailingRaw.trim()
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

/** 适老且更自然的默认播报参数：略慢语速、轻微抬高音高，避免发闷机械感。 */
export const SPEECH_DEFAULTS = { rate: 0.92, pitch: 1.05, volume: 1 } as const

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
  // 自然度优先于“是否本地”：用户明确要求更自然音色；同档时仍偏好本地。
  if (NATURAL_VOICE_PATTERN.test(name)) score += 70
  if (voice.localService) score += 15
  if (PLAIN_LOCAL_VOICE_PATTERN.test(name) && !NATURAL_VOICE_PATTERN.test(name)) {
    score -= 25
  }
  if (ROBOTIC_VOICE_PATTERN.test(name)) score -= 60
  if (voice.default) score += 5
  return score
}

/**
 * 在浏览器已加载的语音里挑一条更自然的中文音色：
 * 普通话 zh-CN 优先；Natural/Neural/晓晓等高质量命名优先于普通本地音色；
 * 同档时本地语音加分；明显机械的引擎降权。
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

  // 提前预热语音列表，缩短首次朗读等待；超时从 1.5s 收紧到 800ms。
export function waitForVoices(synth: SpeechSynthesisLike, timeoutMs = 800): Promise<SpeechVoiceLike[]> {
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
