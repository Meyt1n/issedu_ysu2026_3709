<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import SwitchRow from '@/components/SwitchRow.vue'
import { createSpeaker } from '@/composables/useSpeech'
import {
  AUTO_SEND_PRESETS,
  isSpeechOutputSupported,
  listChineseVoices,
  loadVoicePreferences,
  saveVoicePreferences,
  SILENCE_PRESETS,
  validateWakePhrase,
  WAKE_PHRASE_PRESETS,
  type SpeechVoiceLike,
  type VoicePreferences,
} from '@/composables/useVoiceInput'
import {
  useA11y,
  type FontScale,
  type ThemeMode,
} from '@/stores/accessibility'

const router = useRouter()
const {
  settings,
  setFontScale,
  setHighContrast,
  setVoiceBroadcast,
  setReduceMotion,
  setElderMode,
  setTheme,
  resetAccessibility,
} = useA11y()

const feedbackSpeaker = createSpeaker(() => true)
const voicePrefs = ref<VoicePreferences>(loadVoicePreferences())
const wakePhraseDraft = ref(voicePrefs.value.wakePhrase)
const wakePhraseError = ref('')
const voiceOptions = ref<SpeechVoiceLike[]>([])
const speechOutputSupported = isSpeechOutputSupported()

async function refreshVoiceOptions(): Promise<void> {
  if (!speechOutputSupported) return
  voiceOptions.value = await listChineseVoices()
}

function applyPreferredVoice(name: string): void {
  voicePrefs.value = saveVoicePreferences({ preferredVoiceName: name })
}

onMounted(() => {
  void refreshVoiceOptions()
})

const silencePresetId = computed(() => {
  const match = SILENCE_PRESETS.find(
    preset => preset.silenceMs === voicePrefs.value.silenceMs
      && preset.continuationSilenceMs === voicePrefs.value.continuationSilenceMs,
  )
  return match?.id ?? 'custom'
})

const autoSendPresetId = computed(() => {
  const match = AUTO_SEND_PRESETS.find(preset => preset.delayMs === voicePrefs.value.autoSendDelayMs)
  return match?.id ?? 'custom'
})

function applySilencePreset(presetId: string): void {
  const preset = SILENCE_PRESETS.find(item => item.id === presetId)
  if (!preset) return
  voicePrefs.value = saveVoicePreferences({
    silenceMs: preset.silenceMs,
    continuationSilenceMs: preset.continuationSilenceMs,
  })
}

function applyAutoSendPreset(presetId: string): void {
  const preset = AUTO_SEND_PRESETS.find(item => item.id === presetId)
  if (!preset) return
  voicePrefs.value = saveVoicePreferences({ autoSendDelayMs: preset.delayMs })
}

function toggleVoicePref<K extends keyof VoicePreferences>(key: K, value: VoicePreferences[K]): void {
  voicePrefs.value = saveVoicePreferences({ [key]: value })
}

function applyWakePreset(phrase: string): void {
  wakePhraseDraft.value = phrase
  saveWakePhrase()
}

function saveWakePhrase(): void {
  const checked = validateWakePhrase(wakePhraseDraft.value)
  if (!checked.ok) {
    wakePhraseError.value = checked.message
    wakePhraseDraft.value = voicePrefs.value.wakePhrase
    return
  }
  wakePhraseError.value = ''
  voicePrefs.value = saveVoicePreferences({ wakePhrase: checked.phrase })
  wakePhraseDraft.value = checked.phrase
}

const FONT_OPTIONS: Array<{ value: FontScale; label: string }> = [
  { value: 'standard', label: '标准' },
  { value: 'large', label: '大' },
  { value: 'xlarge', label: '特大' },
]

const THEME_OPTIONS: Array<{ value: ThemeMode; label: string }> = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'auto', label: '跟随系统' },
]

function onElderModeChange(enabled: boolean): void {
  setElderMode(enabled)
  feedbackSpeaker.speak(enabled ? '长辈模式已开启。' : '长辈模式已关闭。')
}

function onVoiceChange(enabled: boolean): void {
  setVoiceBroadcast(enabled)
  if (enabled) feedbackSpeaker.speak('语音播报已开启。')
}

function tryVoice(): void {
  feedbackSpeaker.speak('语音播报已开启，重要提醒会通过语音播报。')
}
</script>

<template>
  <main id="main" class="screen">
    <button type="button" class="btn btn-quiet back-btn" @click="router.back()">
      <AppIcon name="arrow-left" :size="18" />
      返回
    </button>

    <header class="screen-header">
      <p class="eyebrow">无障碍模式</p>
      <h1>无障碍设置</h1>
    </header>

    <section class="card">
      <SwitchRow
        title="长辈模式"
        :model-value="settings.elderMode"
        @update:model-value="onElderModeChange"
      />
    </section>

    <section class="card" aria-labelledby="theme-title">
      <h2 id="theme-title">外观</h2>
      <div class="segmented" role="group" aria-label="选择外观模式">
        <button
          v-for="option in THEME_OPTIONS"
          :key="option.value"
          type="button"
          :aria-pressed="settings.theme === option.value"
          @click="setTheme(option.value)"
        >
          {{ option.label }}
        </button>
      </div>
    </section>

    <section class="card" aria-labelledby="font-title">
      <h2 id="font-title">字号</h2>
      <div class="segmented" role="group" aria-label="选择字号档位">
        <button
          v-for="option in FONT_OPTIONS"
          :key="option.value"
          type="button"
          :aria-pressed="settings.fontScale === option.value"
          @click="setFontScale(option.value)"
        >
          {{ option.label }}
        </button>
      </div>
      <p class="font-preview">示例：请在午后测量血压，并记录收缩压与舒张压。</p>
    </section>

    <section class="card">
      <SwitchRow
        title="高对比度"
        :model-value="settings.highContrast"
        @update:model-value="setHighContrast"
      />
    </section>

    <section class="card">
      <SwitchRow
        title="语音播报"
        :model-value="settings.voiceBroadcast"
        @update:model-value="onVoiceChange"
      />
      <label class="pref-row">
        <span>播报音色</span>
        <select
          :value="voicePrefs.preferredVoiceName"
          :disabled="!speechOutputSupported"
          aria-label="选择播报音色"
          @change="applyPreferredVoice(($event.target as HTMLSelectElement).value)"
        >
          <option value="">自动优选（更自然的中文女声）</option>
          <option v-for="voiceOption in voiceOptions" :key="voiceOption.name" :value="voiceOption.name">
            {{ voiceOption.name }}（{{ voiceOption.lang }}{{ voiceOption.localService ? ' · 本地' : '' }}）
          </option>
        </select>
      </label>
      <h3 class="subheading">助手听写偏好</h3>
      <label class="pref-row">
        <span>唤醒词</span>
        <input
          v-model="wakePhraseDraft"
          type="text"
          maxlength="8"
          aria-label="自定义唤醒词"
          @change="saveWakePhrase"
        />
      </label>
      <div class="wake-presets">
        <button
          v-for="preset in WAKE_PHRASE_PRESETS"
          :key="preset.id"
          type="button"
          class="btn btn-quiet"
          @click="applyWakePreset(preset.phrase)"
        >
          {{ preset.label }}
        </button>
      </div>
      <p v-if="wakePhraseError" class="meta-line wake-error">{{ wakePhraseError }}</p>
      <label class="pref-row">
        <span>静音结束</span>
        <select :value="silencePresetId" @change="applySilencePreset(($event.target as HTMLSelectElement).value)">
          <option v-for="preset in SILENCE_PRESETS" :key="preset.id" :value="preset.id">
            {{ preset.label }}
          </option>
        </select>
      </label>
      <label class="pref-row">
        <span>说完后自动发送</span>
        <select :value="autoSendPresetId" @change="applyAutoSendPreset(($event.target as HTMLSelectElement).value)">
          <option v-for="preset in AUTO_SEND_PRESETS" :key="preset.id" :value="preset.id">
            {{ preset.label }}
          </option>
        </select>
      </label>
      <SwitchRow
        title="听写提示音"
        :model-value="voicePrefs.confirmSound"
        @update:model-value="value => toggleVoicePref('confirmSound', value)"
      />
      <SwitchRow
        title="双次唤醒确认"
        :model-value="voicePrefs.doubleWake"
        @update:model-value="value => toggleVoicePref('doubleWake', value)"
      />
      <SwitchRow
        title="听写后语音指令"
        :model-value="voicePrefs.voiceCommands"
        @update:model-value="value => toggleVoicePref('voiceCommands', value)"
      />
      <div class="voice-actions">
        <button type="button" class="btn btn-quiet" @click="tryVoice">
          <AppIcon name="sound" :size="18" />
          试听一段
        </button>
      </div>
    </section>

    <section class="card">
      <SwitchRow
        title="减少动效"
        :model-value="settings.reduceMotion"
        @update:model-value="setReduceMotion"
      />
    </section>

    <button type="button" class="btn btn-danger btn-block" @click="resetAccessibility">
      恢复默认设置
    </button>

  </main>
</template>

<style scoped>
.back-btn { justify-self: start; }
.font-preview {
  background: var(--well-bg);
  border-radius: 12px;
  padding: 12px 14px;
  color: var(--c-ink-soft);
  box-shadow: inset 0 1px 0 var(--hilite);
}
html[data-contrast='high'] .font-preview { border: 2px solid #000; background: #fff; }
.voice-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.subheading { margin: 12px 0 8px; font-size: 0.95rem; }
.pref-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 0.92rem;
}
.pref-row select {
  min-height: var(--tap);
  border-radius: 10px;
  padding: 8px 10px;
}
.pref-row input {
  flex: 1;
  min-height: var(--tap);
  border-radius: 10px;
  padding: 8px 10px;
}
.wake-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.wake-error { color: var(--danger, #b42318); }
.meta-line { color: var(--c-ink-soft); font-size: 0.9rem; }
</style>
