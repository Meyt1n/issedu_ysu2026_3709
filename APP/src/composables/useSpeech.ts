import { readonly, ref } from 'vue'

import { useA11y } from '@/stores/accessibility'

export interface SpeechLike {
  cancel(): void
  speak(utterance: SpeechSynthesisUtterance): void
  getVoices?(): SpeechSynthesisVoice[]
  addEventListener?(type: 'voiceschanged', listener: () => void): void
  removeEventListener?(type: 'voiceschanged', listener: () => void): void
}

export interface Speaker {
  /** 语音播报开启时朗读文本；每次播报前会打断上一条，避免堆积。 */
  speak(text: string): boolean
  stop(): void
  supported: boolean
}

/** 适老可读的播报参数：语速略慢（与无障碍说明一致），音高音量保持自然。 */
export const SPEECH_DEFAULTS = { rate: 0.95, pitch: 1, volume: 1 } as const

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

function hasChineseVoice(voices: SpeechSynthesisVoice[]): boolean {
  // 部分浏览器延迟加载语音列表；空列表时仍尝试播报，避免误判。
  return voices.length === 0 || voices.some((voice) => /^zh(?:-|_)?/i.test(voice.lang))
}

const NATURAL_VOICE_PATTERN =
  /natural|neural|premium|enhanced|xiaoxiao|xiaoyi|yunxi|yunjian|yunyang|tingting|ting-ting|meijia|mei-jia|晓|云|婷/i
const ROBOTIC_VOICE_PATTERN = /espeak|eloquence|compact|novelty|whisper/i

function chineseVoiceScore(voice: SpeechSynthesisVoice): number {
  const lang = voice.lang.toLowerCase().replace('_', '-')
  if (!lang.startsWith('zh')) return -1
  let score = lang.startsWith('zh-cn') || lang === 'zh' ? 100 : 50
  // 本地语音优先：合成不出网，符合“健康数据默认不出网”的产品承诺。
  if (voice.localService) score += 40
  if (NATURAL_VOICE_PATTERN.test(voice.name)) score += 25
  if (ROBOTIC_VOICE_PATTERN.test(voice.name)) score -= 60
  if (voice.default) score += 5
  return score
}

/**
 * 挑选更自然的中文音色：普通话 zh-CN 优先，其次其他中文；
 * 本地语音优先于联网语音；高质量命名加分、机械引擎降权。
 * 没有中文语音时返回 null，由调用方退回 lang='zh-CN' 兜底。
 */
export function pickChineseVoice(voices: readonly SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  let best: SpeechSynthesisVoice | null = null
  let bestScore = -1
  for (const voice of voices) {
    const score = chineseVoiceScore(voice)
    if (score > bestScore) {
      best = voice
      bestScore = score
    }
  }
  return bestScore >= 0 ? best : null
}

/** 长文本按句切分：规避长 utterance 中途静音，也让“点按停止”更及时。 */
export function splitSpeechSegments(text: string, maxLength = 120): string[] {
  const content = text.trim()
  if (!content) return []
  if (content.length <= maxLength) return [content]

  const sentences = content.match(/[^。！？!?\n]+[。！？!?\n]*/g) ?? [content]
  const segments: string[] = []
  let current = ''
  const flush = () => {
    if (current.trim()) segments.push(current.trim())
    current = ''
  }
  for (const sentence of sentences) {
    if (sentence.length > maxLength) {
      flush()
      const clauses = sentence.match(/[^，、；：,;:]+[，、；：,;:]*/g) ?? [sentence]
      for (const clause of clauses) {
        if (clause.length > maxLength) {
          flush()
          for (let index = 0; index < clause.length; index += maxLength) {
            segments.push(clause.slice(index, index + maxLength).trim())
          }
          continue
        }
        if (current.length + clause.length > maxLength) flush()
        current += clause
      }
      flush()
      continue
    }
    if (current.length + sentence.length > maxLength) flush()
    current += sentence
  }
  flush()
  return segments.filter((segment) => segment.length > 0)
}

function getVoicesSafe(synth: SpeechLike): SpeechSynthesisVoice[] {
  try {
    return synth.getVoices?.() ?? []
  } catch {
    return []
  }
}

/** voices 延迟加载时等待一次 voiceschanged，超时后返回当前列表（可能为空）。 */
function waitForVoices(synth: SpeechLike, timeoutMs = 1200): Promise<SpeechSynthesisVoice[]> {
  const immediate = getVoicesSafe(synth)
  if (immediate.length > 0 || typeof synth.addEventListener !== 'function') {
    return Promise.resolve(immediate)
  }
  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      synth.removeEventListener?.('voiceschanged', finish)
      resolve(getVoicesSafe(synth))
    }
    const timer = setTimeout(finish, timeoutMs)
    synth.addEventListener?.('voiceschanged', finish)
  })
}

function showGuidance(message: string): void {
  speakingText.value = ''
  speechGuidance.value = message
}

const RETRY_GUIDANCE = '语音暂时无法播放。请先轻触页面后重试；若仍无声音，请检查系统“文字转语音”设置。'

/** 工厂函数便于测试注入假的 speechSynthesis 与开关读取函数。 */
export function createSpeaker(
  isEnabled: () => boolean,
  synth: SpeechLike | null = resolveSynth(),
): Speaker {
  // 提前触发一次语音列表加载：部分浏览器首次 getVoices() 才开始异步加载。
  if (synth) getVoicesSafe(synth)

  // 递增令牌：stop 或新播报后，旧播报链上的延迟回调全部失效。
  let token = 0

  function speakSegments(
    activeSynth: SpeechLike,
    text: string,
    segments: string[],
    voice: SpeechSynthesisVoice | null,
    currentToken: number,
    index: number,
  ): void {
    if (currentToken !== token) return
    const segment = segments[index]
    if (!segment) {
      if (speakingText.value === text) speakingText.value = ''
      return
    }
    const utterance = new SpeechSynthesisUtterance(segment)
    utterance.lang = voice?.lang ?? 'zh-CN'
    if (voice) utterance.voice = voice
    utterance.rate = SPEECH_DEFAULTS.rate
    utterance.pitch = SPEECH_DEFAULTS.pitch
    utterance.volume = SPEECH_DEFAULTS.volume
    utterance.onend = () => {
      if (currentToken !== token) return
      if (index + 1 < segments.length) {
        speakSegments(activeSynth, text, segments, voice, currentToken, index + 1)
      } else if (speakingText.value === text) {
        speakingText.value = ''
      }
    }
    utterance.onerror = () => {
      // 被 stop/新播报打断时不提示；真实失败（如首次交互限制）给文字引导。
      if (currentToken !== token) return
      if (speakingText.value === text) speakingText.value = ''
      showGuidance(RETRY_GUIDANCE)
    }
    try {
      activeSynth.speak(utterance)
    } catch {
      if (speakingText.value === text) speakingText.value = ''
      showGuidance(RETRY_GUIDANCE)
    }
  }

  return {
    supported: synth !== null,
    speak(text: string): boolean {
      if (!text.trim() || !isEnabled()) return false
      if (!synth) {
        showGuidance('此设备暂不支持语音播报，请继续阅读屏幕文字。')
        return false
      }
      const loadedVoices = getVoicesSafe(synth)
      if (!hasChineseVoice(loadedVoices)) {
        showGuidance('未发现中文语音。请在系统设置安装中文“文字转语音”后重试。')
        return false
      }
      try {
        synth.cancel()
      } catch {
        // cancel 失败不影响后续核心操作，继续尝试播报。
      }
      token += 1
      const currentToken = token
      const segments = splitSpeechSegments(text.trim())
      speakingText.value = text
      if (loadedVoices.length > 0 || typeof synth.addEventListener !== 'function') {
        speakSegments(synth, text, segments, pickChineseVoice(loadedVoices), currentToken, 0)
      } else {
        void waitForVoices(synth).then((voices) => {
          if (currentToken !== token) return
          speakSegments(synth, text, segments, pickChineseVoice(voices), currentToken, 0)
        })
      }
      return true
    },
    stop(): void {
      token += 1
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
