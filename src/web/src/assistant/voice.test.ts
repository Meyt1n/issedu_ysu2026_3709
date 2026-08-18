import { describe, expect, it } from 'vitest'

import {
  isSpeechInputSupported,
  isSpeechOutputSupported,
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
})
