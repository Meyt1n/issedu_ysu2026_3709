import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearSpeechGuidance,
  createSpeaker,
  useSpeechGuidance,
  type SpeechLike,
} from './useSpeech'

class FakeUtterance {
  text: string
  lang = ''
  rate = 1
  onend: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(text: string) {
    this.text = text
  }
}

vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)

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
    const speaker = createSpeaker(() => true, fakeSynth([{ lang: 'en-US' } as SpeechSynthesisVoice]))
    expect(speaker.speak('测试')).toBe(false)
    expect(useSpeechGuidance().value).toContain('未发现中文语音')
  })

  it('首次交互限制等播报错误时静默降级并给出重试引导', () => {
    const speaker = createSpeaker(() => true, synth)
    speaker.speak('测试')
    synth.spoken[0]!.onerror?.()
    expect(useSpeechGuidance().value).toContain('轻触页面后重试')
  })
})