import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearSpeechGuidance,
  createSpeaker,
  pickChineseVoice,
  splitSpeechSegments,
  useSpeakingIndicator,
  useSpeechGuidance,
  type SpeechLike,
} from './useSpeech'

class FakeUtterance {
  text: string
  lang = ''
  rate = 1
  pitch = 1
  volume = 1
  voice: SpeechSynthesisVoice | null = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(text: string) {
    this.text = text
  }
}

vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)

function fakeVoice(partial: Partial<SpeechSynthesisVoice> & { name: string }): SpeechSynthesisVoice {
  return { lang: 'zh-CN', localService: true, default: false, voiceURI: partial.name, ...partial } as SpeechSynthesisVoice
}

function fakeSynth(voices: SpeechSynthesisVoice[] = []): SpeechLike & { spoken: FakeUtterance[]; cancelCount: number } {
  const record = {
    spoken: [] as FakeUtterance[],
    cancelCount: 0,
    cancel(): void {
      record.cancelCount += 1
    },
    speak(utterance: SpeechSynthesisUtterance): void {
      record.spoken.push(utterance as unknown as FakeUtterance)
    },
    getVoices(): SpeechSynthesisVoice[] {
      return voices
    },
  }
  return record
}

describe('语音播报 composable', () => {
  let synth: ReturnType<typeof fakeSynth>

  beforeEach(() => {
    synth = fakeSynth()
    clearSpeechGuidance()
  })

  it('开关关闭时不播报', () => {
    const speaker = createSpeaker(() => false, synth)
    expect(speaker.speak('测试')).toBe(false)
    expect(synth.spoken.length).toBe(0)
  })

  it('开关开启时以中文播报，并先打断上一条', () => {
    const speaker = createSpeaker(() => true, synth)
    expect(speaker.speak('今天有两项照护任务')).toBe(true)
    expect(synth.cancelCount).toBe(1)
    expect(synth.spoken.length).toBe(1)
    expect(synth.spoken[0]!.text).toBe('今天有两项照护任务')
    expect(synth.spoken[0]!.lang).toBe('zh-CN')
    expect(synth.spoken[0]!.rate).toBeCloseTo(0.95)
    expect(synth.spoken[0]!.pitch).toBeCloseTo(1)
    expect(synth.spoken[0]!.volume).toBeCloseTo(1)
  })

  it('空文本不播报', () => {
    const speaker = createSpeaker(() => true, synth)
    expect(speaker.speak('   ')).toBe(false)
  })

  it('环境不支持语音时安全降级并给出文字引导', () => {
    const speaker = createSpeaker(() => true, null)
    expect(speaker.supported).toBe(false)
    expect(speaker.speak('测试')).toBe(false)
    expect(() => speaker.stop()).not.toThrow()
    expect(useSpeechGuidance().value).toContain('暂不支持')
  })

  it('没有中文语音时不调用播报并给出安装引导', () => {
    const speaker = createSpeaker(() => true, fakeSynth([fakeVoice({ name: 'Samantha', lang: 'en-US' })]))
    expect(speaker.speak('测试')).toBe(false)
    expect(useSpeechGuidance().value).toContain('未发现中文语音')
  })

  it('首次交互限制等播报错误时静默降级并给出重试引导', () => {
    const speaker = createSpeaker(() => true, synth)
    speaker.speak('测试')
    synth.spoken[0]!.onerror?.()
    expect(useSpeechGuidance().value).toContain('轻触页面后重试')
  })

  it('有中文语音时优选本地自然音色并写入 utterance', () => {
    const natural = fakeVoice({ name: 'Xiaoxiao (Natural)' })
    const remote = fakeVoice({ name: 'Google 普通话（中国大陆）', localService: false })
    const withVoices = fakeSynth([remote, natural])
    const speaker = createSpeaker(() => true, withVoices)
    expect(speaker.speak('播报测试')).toBe(true)
    expect(withVoices.spoken[0]!.voice).toBe(natural)
    expect(withVoices.spoken[0]!.lang).toBe('zh-CN')
  })

  it('长文本分段播报，播完最后一段才清空播报指示', () => {
    const speaker = createSpeaker(() => true, synth)
    const text = '这里是一段用于测试的较长中文播报内容。'.repeat(12)
    expect(speaker.speak(text)).toBe(true)
    expect(synth.spoken.length).toBe(1)
    expect(useSpeakingIndicator().value).toBe(text)

    synth.spoken[0]!.onend?.()
    expect(synth.spoken.length).toBeGreaterThan(1)
    expect(useSpeakingIndicator().value).toBe(text)

    while (useSpeakingIndicator().value !== '') {
      const before = synth.spoken.length
      synth.spoken[synth.spoken.length - 1]!.onend?.()
      if (synth.spoken.length === before && useSpeakingIndicator().value !== '') break
    }
    expect(useSpeakingIndicator().value).toBe('')
  })

  it('停止播报后旧分段回调不再续播', () => {
    const speaker = createSpeaker(() => true, synth)
    const text = '这里是一段用于测试的较长中文播报内容。'.repeat(12)
    speaker.speak(text)
    expect(synth.spoken.length).toBe(1)

    speaker.stop()
    expect(useSpeakingIndicator().value).toBe('')
    synth.spoken[0]!.onend?.()
    synth.spoken[0]!.onerror?.()
    expect(synth.spoken.length).toBe(1)
    expect(useSpeechGuidance().value).toBe('')
  })
})

describe('中文音色优选', () => {
  it('本地 zh-CN 优先于联网语音', () => {
    const local = fakeVoice({ name: 'Microsoft Huihui' })
    const remote = fakeVoice({ name: 'Google 普通话（中国大陆）', localService: false })
    expect(pickChineseVoice([remote, local])).toBe(local)
  })

  it('高质量命名加分、机械引擎降权', () => {
    const plain = fakeVoice({ name: 'Microsoft Huihui' })
    const natural = fakeVoice({ name: 'Microsoft Xiaoxiao (Natural)' })
    const robotic = fakeVoice({ name: 'eSpeak Chinese' })
    expect(pickChineseVoice([robotic, plain, natural])).toBe(natural)
  })

  it('没有 zh-CN 时退回其他中文，完全没有中文时返回 null', () => {
    const cantonese = fakeVoice({ name: 'Sin-ji', lang: 'zh-HK' })
    expect(pickChineseVoice([fakeVoice({ name: 'Samantha', lang: 'en-US' }), cantonese])).toBe(cantonese)
    expect(pickChineseVoice([fakeVoice({ name: 'Samantha', lang: 'en-US' })])).toBeNull()
    expect(pickChineseVoice([])).toBeNull()
  })
})

describe('播报分段', () => {
  it('短文本不分段，长文本按句切分且不丢内容', () => {
    expect(splitSpeechSegments('今天有两项照护任务。')).toEqual(['今天有两项照护任务。'])
    const text = '这里是一段用于测试的较长中文播报内容。'.repeat(12)
    const segments = splitSpeechSegments(text, 120)
    expect(segments.length).toBeGreaterThan(1)
    for (const segment of segments) expect(segment.length).toBeLessThanOrEqual(120)
    expect(segments.join('')).toBe(text)
  })
})
