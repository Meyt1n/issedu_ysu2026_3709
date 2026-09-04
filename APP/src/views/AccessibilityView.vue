<script setup lang="ts">
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import SwitchRow from '@/components/SwitchRow.vue'
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
  setReduceMotion,
  setElderMode,
  setTheme,
  resetAccessibility,
} = useA11y()

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
</style>
