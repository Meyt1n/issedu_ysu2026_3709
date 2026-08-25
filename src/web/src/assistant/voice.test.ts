import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  containsWakePhrase,
  createSpeechRecognition,
  isSpeechInputSupported,
  isSpeechOutputSupported,
  latestTranscriptFromEvent,
  normalizeVoiceText,
  pickBestAlternative,
  pickPreferredChineseVoice,
  prepareSpeechText,
  speakText,
  splitSpeechSegments,
  stopSpeaking,
  transcriptAfterWakePhrase,
  transcriptFromEvent,
  waitForVoices,
  type SpeechRecognitionEventLike,
  type SpeechRecognitionResultLike,
  type SpeechSynthesisLike,
  type SpeechVoiceLike,
} from './voice'

function voice(partial: Partial<SpeechVoiceLike> & { name: string }): SpeechVoiceLike {
  return { lang: 'zh-CN', localService: true, default: false, ...partial }
}

class FakeUtterance {
  text: string
  lang = ''
  rate = 1
  pitch = 1
  volume = 1
  voice: SpeechVoiceLike | null = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(text: string) {
    this.text = text
  }
}

interface FakeSynth extends SpeechSynthesisLike {
  voices: SpeechVoiceLike[]
  spoken: FakeUtterance[]
  cancelCount: number
  dispatchVoicesChanged: () => void
}

function fakeSynth(voices: SpeechVoiceLike[] = []): FakeSynth {
  const listeners = new Set<() => void>()
  const synth: FakeSynth = {
    voices,
    spoken: [],
    cancelCount: 0,
    cancel() {
      synth.cancelCount += 1
    },
    speak(utterance) {
      synth.spoken.push(utterance as unknown as FakeUtterance)
    },
    getVoices() {
      return synth.voices
    },
    addEventListener(_type, listener) {
      listeners.add(listener)
    },
    removeEventListener(_type, listener) {
      listeners.delete(listener)
    },
    dispatchVoicesChanged() {
      for (const listener of [...listeners]) listener()
    },
  }
  return synth
}

const previousWindow = (globalThis as { window?: unknown }).window

function stubWindow(value: unknown): void {
  Object.defineProperty(globalThis, 'window', { configurable: true, value })
}

function restoreWindow(): void {
  if (previousWindow === undefined) {
    delete (globalThis as { window?: unknown }).window
  } else {
    Object.defineProperty(globalThis, 'window', { configurable: true, value: previousWindow })
  }
}

afterEach(() => {
  restoreWindow()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('assistant voice capability boundary', () => {
  it('combines browser recognition result fragments without chinese spaces', () => {
    const event = {
      resultIndex: 0,
      results: [
        { isFinal: true, length: 1, 0: { transcript: '最近的用药' } },
        { isFinal: false, length: 1, 0: { transcript: '提醒是什么' } },
      ],
    } as unknown as SpeechRecognitionEventLike

    expect(transcriptFromEvent(event)).toBe('最近的用药提醒是什么')
  })

  it('picks the higher-confidence chinese alternative for accuracy', () => {
    const result = {
      isFinal: true,
      length: 2,
      0: { transcript: 'xiaoyan dakai', confidence: 0.2 },
      1: { transcript: '小燕打开', confidence: 0.9 },
    } as unknown as SpeechRecognitionResultLike
    expect(pickBestAlternative(result)).toBe('小燕打开')
  })

  it('uses the latest interim slice for low-latency wake probing', () => {
    const event = {
      resultIndex: 1,
      results: [
        { isFinal: true, length: 1, 0: { transcript: '背景噪音' } },
        { isFinal: false, length: 1, 0: { transcript: '小燕打开' } },
      ],
    } as unknown as SpeechRecognitionEventLike
    expect(latestTranscriptFromEvent(event)).toBe('小燕打开')
  })

  it('degrades safely when the browser has no speech APIs', () => {
    expect(isSpeechInputSupported()).toBe(false)
    expect(isSpeechOutputSupported()).toBe(false)
    expect(speakText('测试')).toBe(false)
  })

  it('matches the wake phrase without changing the transcript used in the draft', () => {
    expect(normalizeVoiceText('小燕，打开！')).toBe('小燕打开')
    expect(containsWakePhrase('小燕，打开助手')).toBe(true)
    expect(containsWakePhrase('小严打开')).toBe(true)
    expect(containsWakePhrase('晓燕，打开一下')).toBe(true)
    expect(transcriptAfterWakePhrase('小燕，打开，查询最近的用药提醒')).toBe('查询最近的用药提醒')
    expect(transcriptAfterWakePhrase('小严打开查询最近的用药提醒')).toBe('查询最近的用药提醒')
    expect(transcriptAfterWakePhrase('请帮我查一下')).toBe('')
  })

  it('configures continuous interim recognition with multi-alternative accuracy', () => {
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

    stubWindow({ SpeechRecognition: FakeRecognition })
    const recognition = createSpeechRecognition('zh-CN', {
      continuous: true,
      interimResults: true,
    })
    expect(recognition?.continuous).toBe(true)
    expect(recognition?.interimResults).toBe(true)
    expect(recognition?.maxAlternatives).toBe(3)
  })
})

describe('chinese voice preference', () => {
  it('prefers natural remote voices over plain local robotic defaults', () => {
    const localPlain = voice({ name: 'Microsoft Huihui', localService: true })
    const remoteNatural = voice({ name: 'Microsoft Xiaoxiao Online (Natural)', localService: false })
    expect(pickPreferredChineseVoice([localPlain, remoteNatural])).toBe(remoteNatural)
  })

  it('prefers higher quality natural voices among local zh-CN voices', () => {
    const plain = voice({ name: 'Microsoft Huihui' })
    const natural = voice({ name: 'Microsoft Xiaoxiao (Natural)' })
    expect(pickPreferredChineseVoice([plain, natural])).toBe(natural)
  })

  it('downranks clearly robotic engines', () => {
    const robotic = voice({ name: 'eSpeak Chinese' })
    const plain = voice({ name: 'Ting-Ting', localService: false })
    expect(pickPreferredChineseVoice([robotic, plain])).toBe(plain)
  })

  it('falls back to other chinese variants when zh-CN is missing', () => {
    const cantonese = voice({ name: 'Sin-ji', lang: 'zh-HK' })
    const english = voice({ name: 'Samantha', lang: 'en-US' })
    expect(pickPreferredChineseVoice([english, cantonese])).toBe(cantonese)
  })

  it('returns null when no chinese voice exists so lang fallback applies', () => {
    expect(pickPreferredChineseVoice([voice({ name: 'Samantha', lang: 'en-US' })])).toBeNull()
    expect(pickPreferredChineseVoice([])).toBeNull()
  })
})

describe('speech text preparation', () => {
  it('splits long answers into sentence-based segments within the limit', () => {
    const sentence = '这里是一段用于测试的较长中文说明内容。'
    const text = sentence.repeat(12)
    const segments = splitSpeechSegments(text, 120)
    expect(segments.length).toBeGreaterThan(1)
    for (const segment of segments) expect(segment.length).toBeLessThanOrEqual(120)
    expect(segments.join('')).toBe(text)
  })

  it('keeps short texts as one segment and drops empty input', () => {
    expect(splitSpeechSegments('今天有两项照护任务。')).toEqual(['今天有两项照护任务。'])
    expect(splitSpeechSegments('   ')).toEqual([])
  })

  it('hard-splits an oversized clause instead of dropping it', () => {
    const clause = '连'.repeat(300)
    const segments = splitSpeechSegments(clause, 120)
    expect(segments.join('')).toBe(clause)
    for (const segment of segments) expect(segment.length).toBeLessThanOrEqual(120)
  })

  it('strips markdown decorations so they are not read aloud', () => {
    expect(prepareSpeechText('**重点**：`剂量` 请以 #医生# 医嘱为准')).toBe('重点 ： 剂量 请以 医生 医嘱为准')
    expect(prepareSpeechText('第一行\n\n第二行')).toBe('第一行 第二行')
  })
})

describe('waitForVoices', () => {
  it('resolves immediately when voices are already loaded', async () => {
    const synth = fakeSynth([voice({ name: 'Tingting' })])
    await expect(waitForVoices(synth)).resolves.toHaveLength(1)
  })

  it('waits for voiceschanged when the list loads late', async () => {
    const synth = fakeSynth([])
    const pending = waitForVoices(synth)
    synth.voices = [voice({ name: 'Tingting' })]
    synth.dispatchVoicesChanged()
    await expect(pending).resolves.toHaveLength(1)
  })

  it('gives up after the timeout and returns the current list', async () => {
    vi.useFakeTimers()
    const synth = fakeSynth([])
    const pending = waitForVoices(synth, 500)
    await vi.advanceTimersByTimeAsync(600)
    await expect(pending).resolves.toEqual([])
  })
})

describe('speakText output pipeline', () => {
  it('interrupts the previous utterance and applies voice, rate, pitch and volume', () => {
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
    const synth = fakeSynth([
      voice({ name: 'Google 普通话（中国大陆）', localService: false }),
      voice({ name: 'Microsoft Xiaoxiao (Natural)' }),
    ])
    stubWindow({ speechSynthesis: synth })

    expect(speakText('今天有两项照护任务。')).toBe(true)
    expect(synth.cancelCount).toBe(1)
    expect(synth.spoken).toHaveLength(1)
    const utterance = synth.spoken[0]!
    expect(utterance.voice?.name).toBe('Microsoft Xiaoxiao (Natural)')
    expect(utterance.lang).toBe('zh-CN')
    expect(utterance.rate).toBeCloseTo(0.92)
    expect(utterance.pitch).toBeCloseTo(1.05)
    expect(utterance.volume).toBeCloseTo(1)
  })

  it('chains long answers segment by segment and finishes exactly once', () => {
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
    const synth = fakeSynth([voice({ name: 'Tingting' })])
    stubWindow({ speechSynthesis: synth })

    const onFinished = vi.fn()
    const text = '这里是一段用于测试的较长中文说明内容。'.repeat(12)
    expect(speakText(text, onFinished)).toBe(true)
    expect(synth.spoken.length).toBe(1)

    while (synth.spoken.length > 0 && onFinished.mock.calls.length === 0) {
      const current = synth.spoken[synth.spoken.length - 1]!
      const before = synth.spoken.length
      current.onend?.()
      if (synth.spoken.length === before) break
    }
    expect(synth.spoken.length).toBeGreaterThan(1)
    expect(onFinished).toHaveBeenCalledTimes(1)
  })

  it('stopSpeaking cancels the chain and suppresses stale callbacks', () => {
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
    const synth = fakeSynth([voice({ name: 'Tingting' })])
    stubWindow({ speechSynthesis: synth })

    const onFinished = vi.fn()
    const text = '这里是一段用于测试的较长中文说明内容。'.repeat(12)
    speakText(text, onFinished)
    expect(synth.spoken.length).toBe(1)

    stopSpeaking()
    expect(synth.cancelCount).toBe(2)
    synth.spoken[0]!.onend?.()
    synth.spoken[0]!.onerror?.()
    expect(synth.spoken.length).toBe(1)
    expect(onFinished).not.toHaveBeenCalled()
  })

  it('reports finish once when a segment errors mid-way', () => {
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
    const synth = fakeSynth([voice({ name: 'Tingting' })])
    stubWindow({ speechSynthesis: synth })

    const onFinished = vi.fn()
    speakText('短文本播报。', onFinished)
    const utterance = synth.spoken[0]!
    utterance.onerror?.()
    utterance.onend?.()
    expect(onFinished).toHaveBeenCalledTimes(1)
  })

  it('waits for late voices before speaking and then picks the chinese voice', async () => {
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
    const synth = fakeSynth([])
    stubWindow({ speechSynthesis: synth })

    expect(speakText('语音列表延迟加载。')).toBe(true)
    expect(synth.spoken).toHaveLength(0)

    synth.voices = [voice({ name: 'Tingting' })]
    synth.dispatchVoicesChanged()
    await Promise.resolve()
    expect(synth.spoken).toHaveLength(1)
    expect(synth.spoken[0]!.voice?.name).toBe('Tingting')
  })
})
