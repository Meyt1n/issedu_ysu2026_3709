import { describe, expect, it } from 'vitest'

import {
  containsWakePhrase,
  createSpeechRecognition,
  isSpeechInputSupported,
  latestTranscriptFromEvent,
  normalizeVoiceText,
  pickBestAlternative,
  transcriptAfterWakePhrase,
  transcriptFromEvent,
  type SpeechRecognitionEventLike,
  type SpeechRecognitionResultLike,
} from './useVoiceInput'

describe('随身版语音输入', () => {
  it('环境无 SpeechRecognition 时安全降级', () => {
    expect(isSpeechInputSupported()).toBe(false)
    expect(createSpeechRecognition()).toBeNull()
  })

  it('中文片段拼接不加空格，并优选高置信度候选', () => {
    const event = {
      resultIndex: 0,
      results: [
        { isFinal: true, length: 1, 0: { transcript: '最近的用药' } },
        { isFinal: false, length: 1, 0: { transcript: '提醒是什么' } },
      ],
    } as unknown as SpeechRecognitionEventLike
    expect(transcriptFromEvent(event)).toBe('最近的用药提醒是什么')

    const result = {
      isFinal: true,
      length: 2,
      0: { transcript: 'xiaoyan xiaoyan', confidence: 0.2 },
      1: { transcript: '小燕小燕', confidence: 0.9 },
    } as unknown as SpeechRecognitionResultLike
    expect(pickBestAlternative(result)).toBe('小燕小燕')
  })

  it('用最新 interim 探测唤醒，并容忍同音误识', () => {
    const event = {
      resultIndex: 1,
      results: [
        { isFinal: true, length: 1, 0: { transcript: '背景噪音' } },
        { isFinal: false, length: 1, 0: { transcript: '小燕小燕' } },
      ],
    } as unknown as SpeechRecognitionEventLike
    expect(latestTranscriptFromEvent(event)).toBe('小燕小燕')
    expect(normalizeVoiceText('晓燕，晓燕')).toBe('小燕小燕')
    expect(containsWakePhrase('小严小严')).toBe(true)
    expect(containsWakePhrase('小燕啊小燕')).toBe(true)
    expect(transcriptAfterWakePhrase('小燕小燕，查询最近的用药提醒')).toBe('查询最近的用药提醒')
  })

  it('默认启用 continuous / interim / 单候选', () => {
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
      const recognition = createSpeechRecognition('zh-CN', {
        continuous: true,
        interimResults: true,
      })
      expect(recognition?.continuous).toBe(true)
      expect(recognition?.interimResults).toBe(true)
      // 只取一个候选：备选项从 3 降到 1，减少识别处理延迟与浏览器 CPU 占用。
      expect(recognition?.maxAlternatives).toBe(1)
    } finally {
      if (previous === undefined) {
        delete (globalThis as { window?: unknown }).window
      } else {
        Object.defineProperty(globalThis, 'window', { configurable: true, value: previous })
      }
    }
  })
})
