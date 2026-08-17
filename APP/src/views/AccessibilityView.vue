<script setup lang="ts">
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import SwitchRow from '@/components/SwitchRow.vue'
import { createSpeaker } from '@/composables/useSpeech'
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
  feedbackSpeaker.speak('语音播报测试：家健镜会用语音读出重要提醒和操作结果。')
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
      <p class="screen-subtitle">所有设置保存在本机；状态同时用图标和文字表达，不只依赖颜色。</p>
    </header>

    <section class="card">
      <SwitchRow
        title="长辈模式"
        description="一键开启：特大字号 + 语音播报 + 简化导航 + 更大按钮"
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
      <p class="meta-line">深色模式为夜间设计的森林夜配色；跟随系统时会随手机深浅色自动切换。</p>
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
        description="加深文字与边框颜色，适合视力较弱或强光环境"
        :model-value="settings.highContrast"
        @update:model-value="setHighContrast"
      />
    </section>

    <section class="card">
      <SwitchRow
        title="语音播报"
        description="用语音读出今日安排、风险提醒和操作结果（使用手机自带语音）"
        :model-value="settings.voiceBroadcast"
        @update:model-value="onVoiceChange"
      />
      <button type="button" class="btn btn-quiet" @click="tryVoice">
        <AppIcon name="sound" :size="18" />
        试听一段
      </button>
    </section>

    <section class="card">
      <SwitchRow
        title="减少动效"
        description="关闭过渡动画；系统开启“减弱动态效果”时会自动生效"
        :model-value="settings.reduceMotion"
        @update:model-value="setReduceMotion"
      />
    </section>

    <button type="button" class="btn btn-danger btn-block" @click="resetAccessibility">
      恢复默认设置
    </button>

    <footer class="disclaimer">
      语音播报依赖手机系统的中文语音包；若无声音，请在系统设置中检查“文字转语音”。
    </footer>
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
</style>
