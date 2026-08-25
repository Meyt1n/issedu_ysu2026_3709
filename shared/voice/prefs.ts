/** 语音交互本地偏好（不上传、不含健康数据）。 */

import { DEFAULT_WAKE_PHRASE } from './recognition'
import { sanitizeWakePhraseInput, validateWakePhrase } from './wakePhrase'

const PREF_KEY = 'hct-voice-prefs:v1'

export interface VoicePreferences {
  /** 听写静音结束毫秒（短停顿继续 / 长停顿结束的「长」阈值）。 */
  silenceMs: number
  /** 续说提示出现时的延长静音毫秒。 */
  continuationSilenceMs: number
  /** 听写结束后是否播放轻量确认音。 */
  confirmSound: boolean
  /** 需要连续两次识别到唤醒词才进入听写，降低误唤醒。 */
  doubleWake: boolean
  /** 可配置唤醒词（本机偏好，默认小燕小燕）。 */
  wakePhrase: string
  /** 听写结束后是否聆听白名单语音指令（发送/重读等）。 */
  voiceCommands: boolean
}

export const DEFAULT_VOICE_PREFERENCES: VoicePreferences = {
  silenceMs: 2200,
  continuationSilenceMs: 3200,
  confirmSound: true,
  doubleWake: true,
  wakePhrase: DEFAULT_WAKE_PHRASE,
  voiceCommands: true,
}

export const SILENCE_PRESETS = [
  { id: 'short', label: '偏短（约 1.6 秒）', silenceMs: 1600, continuationSilenceMs: 2400 },
  { id: 'standard', label: '标准（约 2.2 秒）', silenceMs: 2200, continuationSilenceMs: 3200 },
  { id: 'long', label: '偏长（约 3.0 秒）', silenceMs: 3000, continuationSilenceMs: 4200 },
] as const

function storage(): Storage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null
  }
}

function normalizeWakePhrase(value: unknown): string {
  if (typeof value !== 'string') return DEFAULT_WAKE_PHRASE
  const checked = validateWakePhrase(value)
  return checked.ok ? checked.phrase : DEFAULT_WAKE_PHRASE
}

export function loadVoicePreferences(): VoicePreferences {
  const target = storage()
  if (!target) return { ...DEFAULT_VOICE_PREFERENCES }
  try {
    const raw = JSON.parse(target.getItem(PREF_KEY) ?? 'null') as Partial<VoicePreferences> | null
    if (!raw || typeof raw !== 'object') return { ...DEFAULT_VOICE_PREFERENCES }
    return {
      silenceMs: typeof raw.silenceMs === 'number' && raw.silenceMs >= 1000 && raw.silenceMs <= 6000
        ? raw.silenceMs
        : DEFAULT_VOICE_PREFERENCES.silenceMs,
      continuationSilenceMs:
        typeof raw.continuationSilenceMs === 'number'
        && raw.continuationSilenceMs >= 1500
        && raw.continuationSilenceMs <= 8000
          ? raw.continuationSilenceMs
          : DEFAULT_VOICE_PREFERENCES.continuationSilenceMs,
      confirmSound: raw.confirmSound !== false,
      doubleWake: raw.doubleWake !== false,
      wakePhrase: normalizeWakePhrase(raw.wakePhrase),
      voiceCommands: raw.voiceCommands !== false,
    }
  } catch {
    return { ...DEFAULT_VOICE_PREFERENCES }
  }
}

export function saveVoicePreferences(prefs: Partial<VoicePreferences>): VoicePreferences {
  const merged = { ...loadVoicePreferences(), ...prefs }
  if (prefs.wakePhrase !== undefined) {
    const checked = validateWakePhrase(sanitizeWakePhraseInput(prefs.wakePhrase))
    merged.wakePhrase = checked.ok ? checked.phrase : loadVoicePreferences().wakePhrase
  }
  try {
    storage()?.setItem(PREF_KEY, JSON.stringify(merged))
  } catch {
    // ignore
  }
  return merged
}
