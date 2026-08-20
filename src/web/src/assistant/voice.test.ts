import { describe, expect, it } from 'vitest'

import {
  containsWakePhrase,
  createSpeechRecognition,
  isSpeechInputSupported,
  isSpeechOutputSupported,
  normalizeVoiceText,
  transcriptAfterWakePhrase,
  transcriptFromEvent,
  type SpeechRecognitionEventLike,
} from './voice'

describe('assistant voice capability boundary', () => {
  it('combines browser recognition result fragments', () => {
    const event = {
      resultIndex: 0,
      results: [
        { isFinal: true, length: 1, 0: { transcript: '最近的用药' } },
        { isFinal: false, length: 1, 0: { transcript: '提醒是什么' } },
      ],
    } as unknown as SpeechRecognitionEventLike

    expect(transcriptFromEvent(event)).toBe('最近的用药 提醒是什么')
  })

  it('degrades safely when the browser has no speech APIs', () => {
    expect(isSpeechInputSupported()).toBe(false)
    expect(isSpeechOutputSupported()).toBe(false)
  })

  it('matches the wake phrase without changing the transcript used in the draft', () => {
    expect(normalizeVoiceText('小燕，打开！')).toBe('小燕打开')
    expect(containsWakePhrase('小燕，打开助手')).toBe(true)
    expect(transcriptAfterWakePhrase('小燕，打开，查询最近的用药提醒')).toBe('查询最近的用药提醒')
    expect(transcriptAfterWakePhrase('请帮我查一下')).toBe('')
  })

  it('configures continuous interim recognition for the wake mode', () => {
    const previousWindow = (globalThis as { window?: unknown }).window
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

    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { SpeechRecognition: FakeRecognition },
    })
    try {
      const recognition = createSpeechRecognition('zh-CN', {
        continuous: true,
        interimResults: true,
        maxAlternatives: 1,
      })
      expect(recognition?.continuous).toBe(true)
      expect(recognition?.interimResults).toBe(true)
      expect(recognition?.maxAlternatives).toBe(1)
    } finally {
      if (previousWindow === undefined) {
        delete (globalThis as { window?: unknown }).window
      } else {
        Object.defineProperty(globalThis, 'window', { configurable: true, value: previousWindow })
      }
    }
  })
})
