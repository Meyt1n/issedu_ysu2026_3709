<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import { PRIVACY_NOTICE_SECTIONS } from '@/stores/privacy'

const emit = defineEmits<{
  /** 用户确认已阅读；写入失败时界面仍会再次展示（fail-closed）。 */
  acknowledged: [ok: boolean]
}>()

function acknowledge(): void {
  emit('acknowledged', true)
}
</script>

<template>
  <div class="privacy-sheet" role="dialog" aria-modal="true" aria-labelledby="privacy-sheet-title">
    <section class="privacy-card">
      <header class="privacy-head">
        <span class="privacy-icon" aria-hidden="true"><AppIcon name="shield" :size="20" /></span>
        <div>
          <p class="eyebrow">使用前请了解</p>
          <h2 id="privacy-sheet-title">隐私与健康数据边界</h2>
        </div>
      </header>

      <div class="privacy-body">
        <section v-for="section in PRIVACY_NOTICE_SECTIONS" :key="section.title" aria-labelledby="nothing">
          <h3>{{ section.title }}</h3>
          <p v-for="line in section.lines" :key="line">{{ line }}</p>
        </section>
      </div>

      <div class="privacy-actions">
        <button type="button" class="btn btn-lg privacy-confirm" @click="acknowledge">
          我已阅读并知晓
        </button>
      </div>
      <p class="meta-line">
        可在“我的”中查看隐私设置。
      </p>
    </section>
  </div>
</template>

<style scoped>
.privacy-sheet {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: max(16px, var(--hct-safe-area-top)) max(16px, var(--hct-safe-area-right))
    max(16px, var(--hct-safe-area-bottom)) max(16px, var(--hct-safe-area-left));
  background: color-mix(in srgb, var(--c-bg) 72%, transparent);
  backdrop-filter: blur(6px);
}
.privacy-card {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  gap: 12px;
  width: min(560px, 100%);
  max-height: min(86vh, 720px);
  overflow: hidden;
  padding: 18px;
  background: var(--c-bg);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: var(--shadow-float);
}
.privacy-head { display: flex; gap: 12px; align-items: center; }
.privacy-icon {
  display: grid; place-items: center;
  width: 44px; height: 44px; border-radius: 50%;
  background: var(--c-calm-soft); color: var(--c-calm-deep);
}
.privacy-head h2 { font-size: 1.15rem; }
.privacy-body { min-height: 0; overflow-y: auto; display: grid; gap: 12px; padding-right: 4px; }
.privacy-body h3 { font-size: 0.98rem; color: var(--c-brand-deep); }
.privacy-body p { line-height: 1.65; font-size: 0.92rem; }
.privacy-actions { display: grid; grid-template-columns: 1fr; gap: 10px; }
.privacy-actions > .btn { min-width: 0; white-space: nowrap; }
@media (max-width: 420px) {
}
html[data-contrast='high'] .privacy-card { border: 2px solid #000; }
html[data-contrast='high'] .privacy-sheet { background: #fff; }
html[data-elder='on'] .privacy-body p { font-size: 1.05rem; }
</style>
