import { readonly, ref } from 'vue'

import { useA11y } from '@/stores/accessibility'

export interface SpeechLike {
  cancel(): void
  speak(utterance: SpeechSynthesisUtterance): void
}

export interface Speaker {
  /** 语音播报开启时朗读文本；每次播报前会打断上一条，避免堆积。 */
  speak(text: string): boolean
  stop(): void
  supported: boolean
}

/** 当前正在播报的文本（空串表示未在播报），供全局指示条使用。 */
const speakingText = ref('')

export function useSpeakingIndicator() {
  return readonly(speakingText)
}

function resolveSynth(): SpeechLike | null {
  if (typeof window === 'undefined') return null
  return window.speechSynthesis ?? null
}

/** 工厂函数便于测试注入假的 speechSynthesis 与开关读取函数。 */
export function createSpeaker(
  isEnabled: () => boolean,
  synth: SpeechLike | null = resolveSynth(),
): Speaker {
  return {
    supported: synth !== null,
    speak(text: string): boolean {
      if (!synth || !isEnabled() || !text.trim()) return false
      synth.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'zh-CN'
      utterance.rate = 0.95
      utterance.onend = () => {
        if (speakingText.value === text) speakingText.value = ''
      }
      utterance.onerror = utterance.onend
      speakingText.value = text
      synth.speak(utterance)
      return true
    },
    stop(): void {
      synth?.cancel()
      speakingText.value = ''
    },
  }
}

let sharedSpeaker: Speaker | null = null

/** 全局共享的播报器：跟随无障碍设置里的“语音播报”开关。 */
export function useSpeech(): Speaker {
  if (!sharedSpeaker) {
    const { settings } = useA11y()
    sharedSpeaker = createSpeaker(() => settings.voiceBroadcast)
  }
  return sharedSpeaker
}
