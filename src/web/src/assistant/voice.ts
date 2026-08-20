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

export function stopSpeaking(): void {
  const currentWindow = speechWindow()
  currentWindow?.speechSynthesis?.cancel()
}

/** Speak only after an explicit user action; no audio is sent to the API. */
export function speakText(text: string, onFinished?: () => void): boolean {
  const currentWindow = speechWindow()
  if (!currentWindow?.speechSynthesis || typeof SpeechSynthesisUtterance === 'undefined') return false
  const content = text.trim()
  if (!content) return false

  currentWindow.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(content)
  utterance.lang = 'zh-CN'
  utterance.rate = 0.95
  utterance.onend = () => onFinished?.()
  utterance.onerror = () => onFinished?.()
  currentWindow.speechSynthesis.speak(utterance)
  return true
}
