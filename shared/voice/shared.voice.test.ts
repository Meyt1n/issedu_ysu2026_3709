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
import {
  containsConfiguredWakePhrase,
  validateWakePhrase,
  WAKE_PHRASE_PRESETS,
} from './wakePhrase'
import { couldBeVoiceCommandPrefix, createAutoSendScheduler, matchVoiceCommand } from './commands'

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
    // 决策 1A：默认句末静音 15 秒；语音回复偏好默认关闭、音色默认自动优选。
    expect(DEFAULT_VOICE_PREFERENCES.silenceMs).toBe(15_000)
    expect(loadVoicePreferences().silenceMs).toBe(15_000)
    expect(loadVoicePreferences().autoSpeakReplies).toBe(false)
    expect(loadVoicePreferences().preferredVoiceName).toBe('')
    expect(loadVoicePreferences().doubleWake).toBe(DEFAULT_VOICE_PREFERENCES.doubleWake)
    const saved = saveVoicePreferences({
      confirmSound: false,
      doubleWake: false,
      silenceMs: 3000,
      autoSpeakReplies: true,
      preferredVoiceName: 'Microsoft Xiaoxiao (Natural)',
    })
    expect(saved.confirmSound).toBe(false)
    expect(saved.doubleWake).toBe(false)
    expect(loadVoicePreferences().silenceMs).toBe(3000)
    expect(loadVoicePreferences().autoSpeakReplies).toBe(true)
    expect(loadVoicePreferences().preferredVoiceName).toBe('Microsoft Xiaoxiao (Natural)')
    vi.unstubAllGlobals()
  })

  it('migrates v1 preferences to v2 and upgrades the stock 2.2s silence to 15s', () => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value) },
      removeItem: (key: string) => { store.delete(key) },
      clear: () => store.clear(),
      key: (index: number) => [...store.keys()][index] ?? null,
      get length() { return store.size },
    })
    store.set('hct-voice-prefs:v1', JSON.stringify({
      silenceMs: 2200,
      continuationSilenceMs: 3200,
      confirmSound: false,
      wakePhrase: '家健镜',
    }))
    const migrated = loadVoicePreferences()
    expect(migrated.silenceMs).toBe(15_000)
    expect(migrated.continuationSilenceMs).toBe(18_000)
    expect(migrated.confirmSound).toBe(false)
    expect(migrated.wakePhrase).toBe('家健镜')
    expect(store.has('hct-voice-prefs:v1')).toBe(false)
    expect(store.has('hct-voice-prefs:v2')).toBe(true)
    vi.unstubAllGlobals()
  })

  it('keeps deliberately customised v1 silence values during migration', () => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value) },
      removeItem: (key: string) => { store.delete(key) },
      clear: () => store.clear(),
      key: (index: number) => [...store.keys()][index] ?? null,
      get length() { return store.size },
    })
    store.set('hct-voice-prefs:v1', JSON.stringify({ silenceMs: 3000, continuationSilenceMs: 4200 }))
    const migrated = loadVoicePreferences()
    expect(migrated.silenceMs).toBe(3000)
    expect(migrated.continuationSilenceMs).toBe(4200)
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
    expect(DICTATION_SILENCE_MS).toBe(15_000)
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

describe('dictation continuation (决策 1A / 根因 B)', () => {
  interface FakeInstance {
    onstart: (() => void) | null
    onresult: ((event: SpeechRecognitionEventLike) => void) | null
    onend: (() => void) | null
    start: () => void
    stop: () => void
    abort: () => void
  }

  function setupFakeRecognition(): { instances: FakeInstance[]; restore: () => void } {
    const instances: FakeInstance[] = []
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
    return {
      instances,
      restore: () => {
        if (previous === undefined) delete (globalThis as { window?: unknown }).window
        else Object.defineProperty(globalThis, 'window', { configurable: true, value: previous })
      },
    }
  }

  function resultEvent(transcript: string): SpeechRecognitionEventLike {
    return {
      resultIndex: 0,
      results: [{ isFinal: true, length: 1, 0: { transcript, confidence: 1 } }],
    } as unknown as SpeechRecognitionEventLike
  }

  it('a 10s pause does not finish the utterance; follow-up speech accumulates', () => {
    vi.useFakeTimers()
    const { instances, restore } = setupFakeRecognition()
    const modes: string[] = []
    let draft = ''
    try {
      const controller = createDictationController({
        onModeChange: (mode) => modes.push(mode),
        onDraft: (text) => {
          draft = text
        },
      }, {
        getPreferences: () => ({
          ...DEFAULT_VOICE_PREFERENCES,
          doubleWake: false,
          silenceMs: 15_000,
          continuationSilenceMs: 18_000,
        }),
      })
      controller.startWake()
      const active = instances[0]!
      active.onresult?.(resultEvent('小燕小燕今天血压有点高'))
      expect(modes).toContain('active')
      vi.advanceTimersByTime(10_000)
      expect(modes.at(-1)).toBe('active')
      active.onresult?.(resultEvent('小燕小燕今天血压有点高 还需要复测吗'))
      vi.advanceTimersByTime(10_000)
      expect(modes.at(-1)).toBe('active')
      expect(draft).toContain('还需要复测吗')
      vi.advanceTimersByTime(5100)
      expect(modes.at(-1)).toBe('ready')
      controller.dispose()
    } finally {
      vi.useRealTimers()
      restore()
    }
  })

  it('open-domain speech during command listening returns to active and accumulates the draft', () => {
    vi.useFakeTimers()
    const { instances, restore } = setupFakeRecognition()
    const modes: string[] = []
    let draft = ''
    const commands: string[] = []
    try {
      const controller = createDictationController({
        onModeChange: (mode) => modes.push(mode),
        onDraft: (text) => {
          draft = text
        },
        onCommand: (command) => commands.push(command),
      }, {
        getPreferences: () => ({
          ...DEFAULT_VOICE_PREFERENCES,
          doubleWake: false,
          voiceCommands: true,
          silenceMs: 15_000,
          continuationSilenceMs: 18_000,
        }),
      })
      controller.startWake()
      instances[0]!.onresult?.(resultEvent('小燕小燕查询用药提醒'))
      vi.advanceTimersByTime(15_050)
      expect(modes.at(-1)).toBe('ready')
      // 400ms 后进入指令聆听
      vi.advanceTimersByTime(450)
      expect(modes.at(-1)).toBe('command')
      const commandSession = instances.at(-1)!
      // 疑似指令前缀：继续等待，不回流
      commandSession.onresult?.(resultEvent('上一条再说'))
      expect(modes.at(-1)).toBe('command')
      // 开放域语音：回到听写态并累加进草稿，不丢弃
      commandSession.onresult?.(resultEvent('另外血压药还要吃几天'))
      expect(modes.at(-1)).toBe('active')
      expect(draft).toContain('查询用药提醒')
      expect(draft).toContain('另外血压药还要吃几天')
      expect(commands).toEqual([])
      controller.dispose()
    } finally {
      vi.useRealTimers()
      restore()
    }
  })
})

describe('wake phrase and voice commands', () => {
  it('validates custom wake phrase length and accepts presets', () => {
    expect(validateWakePhrase('家健镜').ok).toBe(true)
    expect(validateWakePhrase('a').ok).toBe(false)
    expect(WAKE_PHRASE_PRESETS.some(p => p.phrase === '家健镜')).toBe(true)
  })

  it('matches configured wake phrase with near-homophones for 家健镜', () => {
    expect(containsConfiguredWakePhrase('家建镜查询用药', '家健镜')).toBe(true)
    expect(containsConfiguredWakePhrase('加健静今天血压', '家健镜')).toBe(true)
    expect(containsConfiguredWakePhrase('小燕小燕', '家健镜')).toBe(false)
  })

  it('matches whitelist voice commands and ignores open-domain phrases', () => {
    expect(matchVoiceCommand('发送吧')).toBe('confirm_send')
    expect(matchVoiceCommand('上一条再说一遍')).toBe('repeat_answer')
    expect(matchVoiceCommand('停止朗读')).toBe('stop_speaking')
    expect(matchVoiceCommand('帮我查一下血压')).toBe(null)
    expect(matchVoiceCommand('打开药盒拍照')).toBe(null)
    expect(matchVoiceCommand('今天天气怎么样')).toBe(null)
  })

  it('detects possible command prefixes so half-spoken commands are not hijacked into the draft', () => {
    expect(couldBeVoiceCommandPrefix('上一条再说')).toBe(true)
    expect(couldBeVoiceCommandPrefix('发')).toBe(true)
    expect(couldBeVoiceCommandPrefix('停止')).toBe(true)
    expect(couldBeVoiceCommandPrefix('血压')).toBe(false)
    expect(couldBeVoiceCommandPrefix('另外我想问')).toBe(false)
    expect(couldBeVoiceCommandPrefix('')).toBe(false)
  })

  it('createAutoSendScheduler sends after quiet delay and can cancel', () => {
    vi.useFakeTimers()
    const sent: string[] = []
    const ticks: number[] = []
    const gate = createAutoSendScheduler({
      delayMs: 3000,
      onTick: (ms) => ticks.push(ms),
      onAutoSend: (draft) => sent.push(draft),
    })
    expect(gate.start('查询用药提醒')).toBe(true)
    expect(gate.isPending()).toBe(true)
    vi.advanceTimersByTime(2990)
    expect(sent).toEqual([])
    vi.advanceTimersByTime(20)
    expect(sent).toEqual(['查询用药提醒'])
    expect(gate.isPending()).toBe(false)

    gate.start('第二句')
    gate.cancel()
    vi.advanceTimersByTime(5000)
    expect(sent).toEqual(['查询用药提醒'])
    vi.useRealTimers()
  })
})
