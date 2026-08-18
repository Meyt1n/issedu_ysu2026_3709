import { readonly, ref } from 'vue'

import { useA11y } from '@/stores/accessibility'

export interface SpeechLike {
  cancel(): void
  speak(utterance: SpeechSynthesisUtterance): void
  getVoices?(): SpeechSynthesisVoice[]
}

export interface Speaker {
  /** 语音播报开启时朗读文本；每次播报前会打断上一条，避免堆积。 */
  speak(text: string): boolean
  stop(): void
  supported: boolean
}

/** 当前正在播报的文本（空串表示未在播报），供全局指示条使用。 */
const speakingText = ref('')
const speechGuidance = ref('')

export function useSpeakingIndicator() {
  return readonly(speakingText)
}

/** 语音不可用时给出的文字引导；播报失败不能阻塞页面操作。 */
export function useSpeechGuidance() {
  return readonly(speechGuidance)
}

export function clearSpeechGuidance(): void {
  speechGuidance.value = ''
}

function resolveSynth(): SpeechLike | null {
  if (typeof window === 'undefined') return null
  return window.speechSynthesis ?? null
}

function hasChineseVoice(synth: SpeechLike): boolean {
  const voices = synth.getVoices?.() ?? []
  // 部分浏览器延迟加载语音列表；空列表时仍尝试播报，避免误判。
  return voices.length === 0 || voices.some((voice) => /^zh(?:-|_)/i.test(voice.lang))
}

function showGuidance(message: string): void {
  speakingText.value = ''
  speechGuidance.value = message
}

/** 工厂函数便于测试注入假的 speechSynthesis 与开关读取函数。 */
export function createSpeaker(
  isEnabled: () => boolean,
  synth: SpeechLike | null = resolveSynth(),
): Speaker {
  return {
    supported: synth !== null,
    speak(text: string): boolean {
      if (!text.trim() || !isEnabled()) return false
      if (!synth) {
        showGuidance('此设备暂不支持语音播报，请继续阅读屏幕文字。')
        return false
      }
      if (!hasChineseVoice(synth)) {
        showGuidance('未发现中文语音。请在系统设置安装中文“文字转语音”后重试。')
        return false
      }
      try {
        synth.cancel()
      } catch {
        // cancel 失败不影响后续核心操作，继续尝试播报。
      }
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'zh-CN'
      utterance.rate = 0.95
      utterance.onend = () => {
        if (speakingText.value === text) speakingText.value = ''
      }
      utterance.onerror = () => {
        if (speakingText.value === text) speakingText.value = ''
        showGuidance('语音暂时无法播放。请先轻触页面后重试；若仍无声音，请检查系统“文字转语音”设置。')
      }
      speakingText.value = text
      try {
        synth.speak(utterance)
        return true
      } catch {
        showGuidance('语音暂时无法播放。请先轻触页面后重试；若仍无声音，请检查系统“文字转语音”设置。')
        return false
      }
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