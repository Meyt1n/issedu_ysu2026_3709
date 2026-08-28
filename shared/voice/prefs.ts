/** 语音交互本地偏好（不上传、不含健康数据）。 */

import { DEFAULT_WAKE_PHRASE } from './recognition'
import { sanitizeWakePhraseInput, validateWakePhrase } from './wakePhrase'

const PREF_KEY = 'hct-voice-prefs:v2'
const LEGACY_PREF_KEY_V1 = 'hct-voice-prefs:v1'

/** v1 时代的默认静音阈值：迁移时视为「用户未主动定制」，升级到 15s 句末静音。 */
const LEGACY_DEFAULT_SILENCE_MS = 2200
const LEGACY_DEFAULT_CONTINUATION_SILENCE_MS = 3200

export const SILENCE_MS_MIN = 1000
export const SILENCE_MS_MAX = 30_000
export const CONTINUATION_SILENCE_MS_MIN = 1500
export const CONTINUATION_SILENCE_MS_MAX = 36_000

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
  /** 听写结束后无新输入，等待多久自动发送（毫秒）。 */
  autoSendDelayMs: number
  /** 助手回答完成后是否自动语音播报（可随时打断）。 */
  autoSpeakReplies: boolean
  /** 首选播报音色名称；空串表示自动优选更自然的中文女声。 */
  preferredVoiceName: string
}

export const DEFAULT_VOICE_PREFERENCES: VoicePreferences = {
  silenceMs: 15_000,
  continuationSilenceMs: 18_000,
  confirmSound: true,
  doubleWake: false,
  wakePhrase: DEFAULT_WAKE_PHRASE,
  voiceCommands: true,
  autoSendDelayMs: 3000,
  autoSpeakReplies: false,
  preferredVoiceName: '',
}

export const AUTO_SEND_PRESETS = [
  { id: 'off', label: '不自动发送', delayMs: 0 },
  { id: 'short', label: '约 2 秒后发送', delayMs: 2000 },
  { id: 'standard', label: '约 3 秒后发送', delayMs: 3000 },
  { id: 'long', label: '约 5 秒后发送', delayMs: 5000 },
] as const

export const SILENCE_PRESETS = [
  { id: 'short', label: '很快（约 1.6 秒）', silenceMs: 1600, continuationSilenceMs: 2400 },
  { id: 'standard', label: '较快（约 2.2 秒）', silenceMs: 2200, continuationSilenceMs: 3200 },
  { id: 'long', label: '适中（约 3.0 秒）', silenceMs: 3000, continuationSilenceMs: 4200 },
  { id: 'sentence', label: '句末（约 15 秒，默认）', silenceMs: 15_000, continuationSilenceMs: 18_000 },
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

function normalizePreferredVoiceName(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value.trim().slice(0, 120)
}

function sanitizePreferences(raw: Partial<VoicePreferences> | null): VoicePreferences {
  if (!raw || typeof raw !== 'object') return { ...DEFAULT_VOICE_PREFERENCES }
  return {
    silenceMs:
      typeof raw.silenceMs === 'number'
      && raw.silenceMs >= SILENCE_MS_MIN
      && raw.silenceMs <= SILENCE_MS_MAX
        ? raw.silenceMs
        : DEFAULT_VOICE_PREFERENCES.silenceMs,
    continuationSilenceMs:
      typeof raw.continuationSilenceMs === 'number'
      && raw.continuationSilenceMs >= CONTINUATION_SILENCE_MS_MIN
      && raw.continuationSilenceMs <= CONTINUATION_SILENCE_MS_MAX
        ? raw.continuationSilenceMs
        : DEFAULT_VOICE_PREFERENCES.continuationSilenceMs,
    confirmSound: raw.confirmSound !== false,
    doubleWake: raw.doubleWake === true,
    wakePhrase: normalizeWakePhrase(raw.wakePhrase),
    voiceCommands: raw.voiceCommands !== false,
    autoSendDelayMs:
      typeof raw.autoSendDelayMs === 'number'
      && raw.autoSendDelayMs >= 0
      && raw.autoSendDelayMs <= 10_000
        ? raw.autoSendDelayMs
        : DEFAULT_VOICE_PREFERENCES.autoSendDelayMs,
    autoSpeakReplies: raw.autoSpeakReplies === true,
    preferredVoiceName: normalizePreferredVoiceName(raw.preferredVoiceName),
  }
}

/**
 * v1→v2 迁移：v1 的默认 2.2s 静音是「未定制」存量，统一升级到 15s 句末静音；
 * 用户主动改过的其他值保留（仍按新钳制范围校验）。
 */
function migrateLegacyPreferences(target: Storage): VoicePreferences | null {
  let legacyRaw: Partial<VoicePreferences> | null = null
  try {
    legacyRaw = JSON.parse(target.getItem(LEGACY_PREF_KEY_V1) ?? 'null') as Partial<VoicePreferences> | null
  } catch {
    legacyRaw = null
  }
  if (!legacyRaw || typeof legacyRaw !== 'object') return null
  const upgraded: Partial<VoicePreferences> = { ...legacyRaw }
  if (typeof legacyRaw.silenceMs !== 'number' || legacyRaw.silenceMs === LEGACY_DEFAULT_SILENCE_MS) {
    upgraded.silenceMs = DEFAULT_VOICE_PREFERENCES.silenceMs
  }
  if (
    typeof legacyRaw.continuationSilenceMs !== 'number'
    || legacyRaw.continuationSilenceMs === LEGACY_DEFAULT_CONTINUATION_SILENCE_MS
  ) {
    upgraded.continuationSilenceMs = DEFAULT_VOICE_PREFERENCES.continuationSilenceMs
  }
  const migrated = sanitizePreferences(upgraded)
  try {
    target.setItem(PREF_KEY, JSON.stringify(migrated))
    target.removeItem(LEGACY_PREF_KEY_V1)
  } catch {
    // 迁移失败也不影响本次读取。
  }
  return migrated
}

export function loadVoicePreferences(): VoicePreferences {
  const target = storage()
  if (!target) return { ...DEFAULT_VOICE_PREFERENCES }
  try {
    const raw = JSON.parse(target.getItem(PREF_KEY) ?? 'null') as Partial<VoicePreferences> | null
    if (!raw || typeof raw !== 'object') {
      const migrated = migrateLegacyPreferences(target)
      return migrated ?? { ...DEFAULT_VOICE_PREFERENCES }
    }
    return sanitizePreferences(raw)
  } catch {
    return { ...DEFAULT_VOICE_PREFERENCES }
  }
}

export function saveVoicePreferences(prefs: Partial<VoicePreferences>): VoicePreferences {
  const merged = sanitizePreferences({ ...loadVoicePreferences(), ...prefs })
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
