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
  onstart: (() => void) | null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

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

export function createSpeechRecognition(lang = 'zh-CN'): SpeechRecognitionLike | null {
  const currentWindow = speechWindow()
  const Constructor = currentWindow?.SpeechRecognition ?? currentWindow?.webkitSpeechRecognition
  if (!Constructor) return null

  const recognition = new Constructor()
  recognition.lang = lang
  recognition.continuous = false
  recognition.interimResults = true
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
