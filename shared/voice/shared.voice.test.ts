import { describe, expect, it, vi } from 'vitest'

import { applyHotwordCorrections, endsWithContinuationCue, memberNameHotwordPairs } from './hotwords'
import {
  containsWakePhrase,
  createSpeechRecognition,
  DEFAULT_WAKE_PHRASE,
  DICTATION_SILENCE_MS,
  latestTranscriptFromEvent,
  normalizeVoiceText,
  pickBestAlternative,
  transcriptAfterWakePhrase,
  transcriptFromEvent,
  type SpeechRecognitionEventLike,
  type SpeechRecognitionResultLike,
} from './recognition'
import { createDictationController } from './dictation'
import { loadChatSession, saveChatSession, clearChatSession } from './chatSession'
import { loadVoicePreferences, saveVoicePreferences, DEFAULT_VOICE_PREFERENCES } from './prefs'
import { splitSpeechSegments } from './tts'

describe('shared voice recognition', () => {
  it('uses 小燕小燕 as the default wake phrase', () => {
    expect(DEFAULT_WAKE_PHRASE).toBe('小燕小燕')
    expect(containsWakePhrase('小严小严')).toBe(true)
    expect(normalizeVoiceText('晓燕，晓燕')).toBe('小燕小燕')
    expect(transcriptAfterWakePhrase('小燕小燕查询用药提醒')).toBe('查询用药提醒')
  })

  it('joins chinese fragments and prefers high-confidence alternatives', () => {
    const event = {
      resultIndex: 0,
      results: [
        { isFinal: true, length: 1, 0: { transcript: '最近的用药' } },
        { isFinal: false, length: 1, 0: { transcript: '提醒是什么' } },
      ],
    } as unknown as SpeechRecognitionEventLike
    expect(transcriptFromEvent(event)).toBe('最近的用药提醒是什么')
    expect(latestTranscriptFromEvent({
      resultIndex: 1,
      results: [
        { isFinal: true, length: 1, 0: { transcript: '噪音' } },
        { isFinal: false, length: 1, 0: { transcript: '小燕小燕' } },
      ],
    } as unknown as SpeechRecognitionEventLike)).toBe('小燕小燕')
    expect(pickBestAlternative({
      isFinal: true,
      length: 2,
      0: { transcript: 'x', confidence: 0.1 },
      1: { transcript: '小燕小燕', confidence: 0.9 },
    } as unknown as SpeechRecognitionResultLike)).toBe('小燕小燕')
  })

  it('configures multi-alternative recognition', () => {
    class FakeRecognition {
      lang = ''
      continuous = false
      interimResults = false
      maxAlternatives = 0
      onstart = null
      onresult = null
      onerror = null
      onend = null
      start = () => undefined
      stop = () => undefined
      abort = () => undefined
    }
    const previous = (globalThis as { window?: unknown }).window
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { SpeechRecognition: FakeRecognition },
    })
    try {
      const recognition = createSpeechRecognition('zh-CN', { continuous: true, interimResults: true })
      expect(recognition?.maxAlternatives).toBe(3)
    } finally {
      if (previous === undefined) delete (globalThis as { window?: unknown }).window
      else Object.defineProperty(globalThis, 'window', { configurable: true, value: previous })
    }
  })
})

describe('hotwords and chat session', () => {
  it('applies domain hotword corrections for draft display', () => {
    expect(applyHotwordCorrections('请查看用药提心')).toBe('请查看用药提醒')
    expect(applyHotwordCorrections('打开药合')).toBe('打开药盒')
  })

  it('builds member-name hotword pairs without persisting names in shared constants', () => {
    const pairs = memberNameHotwordPairs(['王秀兰', ''])
    expect(pairs.length).toBeGreaterThan(0)
    expect(applyHotwordCorrections('请帮王秀兰查用药提醒', pairs)).toContain('王秀兰')
  })

  it('extends silence when draft ends with continuation cue', () => {
    expect(endsWithContinuationCue('今天还有')).toBe(true)
    expect(endsWithContinuationCue('今天还有任务')).toBe(false)
  })

  it('loads and saves voice preferences locally', () => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value) },
      removeItem: (key: string) => { store.delete(key) },
      clear: () => store.clear(),
      key: (index: number) => [...store.keys()][index] ?? null,
      get length() { return store.size },
    })
    expect(loadVoicePreferences().doubleWake).toBe(DEFAULT_VOICE_PREFERENCES.doubleWake)
    const saved = saveVoicePreferences({ confirmSound: false, doubleWake: false, silenceMs: 3000 })
    expect(saved.confirmSound).toBe(false)
    expect(saved.doubleWake).toBe(false)
    expect(loadVoicePreferences().silenceMs).toBe(3000)
    vi.unstubAllGlobals()
  })

  it('supports optional double-wake before entering dictation', () => {
    vi.useFakeTimers()
    const instances: Array<{
      onresult: ((event: SpeechRecognitionEventLike) => void) | null
      start: () => void
      stop: () => void
      abort: () => void
    }> = []
    class FakeRecognition {
      onstart: (() => void) | null = null
      onresult: ((event: SpeechRecognitionEventLike) => void) | null = null
      onerror: ((event: { error?: string }) => void) | null = null
      onend: (() => void) | null = null
      lang = ''
      continuous = false
      interimResults = false
      maxAlternatives = 0
      constructor() {
        instances.push(this)
      }
      start = () => {
        this.onstart?.()
      }
      stop = () => undefined
      abort = () => undefined
    }
    const previous = (globalThis as { window?: unknown }).window
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { SpeechRecognition: FakeRecognition },
    })
    const modes: string[] = []
    try {
      const controller = createDictationController({
        onModeChange: (mode) => modes.push(mode),
      }, {
        getPreferences: () => ({ ...DEFAULT_VOICE_PREFERENCES, doubleWake: true }),
      })
      controller.startWake()
      const active = instances[0]!
      active.onresult?.({
        resultIndex: 0,
        results: [{ isFinal: true, length: 1, 0: { transcript: '小燕小燕', confidence: 1 } }],
      } as unknown as SpeechRecognitionEventLike)
      expect(modes).not.toContain('active')
      active.onresult?.({
        resultIndex: 0,
        results: [{ isFinal: true, length: 1, 0: { transcript: '小燕小燕查询', confidence: 1 } }],
      } as unknown as SpeechRecognitionEventLike)
      expect(modes).toContain('active')
      controller.dispose()
    } finally {
      vi.useRealTimers()
      if (previous === undefined) delete (globalThis as { window?: unknown }).window
      else Object.defineProperty(globalThis, 'window', { configurable: true, value: previous })
    }
  })

  it('isolates chat sessions by actor/household/member', () => {
    const store = new Map<string, string>()
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value) },
      removeItem: (key: string) => { store.delete(key) },
      clear: () => store.clear(),
      key: (index: number) => [...store.keys()][index] ?? null,
      get length() { return store.size },
    })
    saveChatSession('a1', 'h1', 'm1', [{ role: 'user', content: '成员一' }])
    saveChatSession('a1', 'h1', 'm2', [{ role: 'user', content: '成员二' }])
    expect(loadChatSession('a1', 'h1', 'm1')[0]?.content).toBe('成员一')
    expect(loadChatSession('a1', 'h1', 'm2')[0]?.content).toBe('成员二')
    clearChatSession('a1', 'h1', 'm1')
    expect(loadChatSession('a1', 'h1', 'm1')).toEqual([])
    expect(loadChatSession('a1', 'h1', 'm2')[0]?.content).toBe('成员二')
    vi.unstubAllGlobals()
  })

  it('splits long speech text', () => {
    const text = '这里是一段用于测试的较长中文说明内容。'.repeat(12)
    const segments = splitSpeechSegments(text, 120)
    expect(segments.length).toBeGreaterThan(1)
    expect(segments.join('')).toBe(text)
  })

  it('dictation silence timeout finishes utterance into ready mode', () => {
    expect(DICTATION_SILENCE_MS).toBe(1600)
    vi.useFakeTimers()
    const instances: Array<{
      onstart: (() => void) | null
      onresult: ((event: SpeechRecognitionEventLike) => void) | null
      onend: (() => void) | null
      start: () => void
      stop: () => void
      abort: () => void
    }> = []
    class FakeRecognition {
      lang = ''
      continuous = false
      interimResults = false
      maxAlternatives = 0
      onstart: (() => void) | null = null
      onresult: ((event: SpeechRecognitionEventLike) => void) | null = null
      onerror: ((event: { error?: string }) => void) | null = null
      onend: (() => void) | null = null
      constructor() {
        instances.push(this)
      }
      start = () => {
        this.onstart?.()
      }
      stop = () => {
        this.onend?.()
      }
      abort = () => {
        this.onend?.()
      }
    }
    const previous = (globalThis as { window?: unknown }).window
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { SpeechRecognition: FakeRecognition },
    })
    const modes: string[] = []
    let draft = ''
    let complete = ''
    try {
      const controller = createDictationController({
        onModeChange: (mode) => modes.push(mode),
        onDraft: (text) => {
          draft = text
        },
        onUtteranceComplete: (text) => {
          complete = text
        },
      }, {
        getPreferences: () => ({
          ...DEFAULT_VOICE_PREFERENCES,
          doubleWake: false,
          silenceMs: DICTATION_SILENCE_MS,
          continuationSilenceMs: DICTATION_SILENCE_MS,
        }),
      })
      controller.startWake()
      const active = instances[0]!
      active.onresult?.({
        resultIndex: 0,
        results: [
          { isFinal: true, length: 1, 0: { transcript: '小燕小燕查询用药提醒', confidence: 1 } },
        ],
      } as unknown as SpeechRecognitionEventLike)
      expect(draft).toContain('查询用药提醒')
      expect(modes).toContain('active')
      vi.advanceTimersByTime(DICTATION_SILENCE_MS + 50)
      expect(modes.at(-1)).toBe('ready')
      expect(complete).toContain('查询用药提醒')
      controller.dispose()
    } finally {
      vi.useRealTimers()
      if (previous === undefined) delete (globalThis as { window?: unknown }).window
      else Object.defineProperty(globalThis, 'window', { configurable: true, value: previous })
    }
  })
})
