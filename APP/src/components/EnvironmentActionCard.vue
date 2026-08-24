<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import type { EnvironmentActionState } from '@/data/types'
import { formatDateTime } from '@/utils/format'

defineProps<{ state: EnvironmentActionState }>()
</script>

<template>
  <section class="card environment-card" aria-labelledby="environment-title">
    <div class="environment-heading">
      <span class="icon-disc" data-tone="info" aria-hidden="true"><AppIcon name="heart" :size="20" /></span>
      <div><h2 id="environment-title">环境行动</h2><p class="meta-line">低风险生活安排，不构成医疗建议或紧急提醒。</p></div>
    </div>
    <template v-if="state.availability === 'AVAILABLE' && state.card">
      <p class="environment-action">{{ state.card.action }}</p>
      <dl class="environment-meta">
        <div><dt>来源</dt><dd>{{ state.card.source }}</dd></div><div><dt>生成时间</dt><dd>{{ formatDateTime(state.card.generatedAt) }}</dd></div>
        <div><dt>有效至</dt><dd>{{ formatDateTime(state.card.validUntil) }}</dd></div><div><dt>规则/配置</dt><dd>{{ state.card.ruleVersion }} / {{ state.card.configVersion }}</dd></div>
      </dl>
      <p class="meta-line">查看依据仅限服务端已授权的环境行动结果；应用不会调整用药、剂量或诊断。</p>
    </template>
    <p v-else class="meta-line" role="status">{{ state.reason }}</p>
  </section>
</template>

<style scoped>
.environment-card { margin-top: 10px; display: grid; gap: 12px; }.environment-heading { display: flex; align-items: flex-start; gap: 10px; }h2 { margin: 0; font-size: 1rem; }.environment-action { margin: 0; font-weight: 750; line-height: 1.5; }.environment-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 0; }.environment-meta div { min-width: 0; }dt { color: var(--c-ink-faint); font-size: 0.78rem; }dd { margin: 2px 0 0; color: var(--c-ink-soft); font-size: 0.82rem; overflow-wrap: anywhere; }@media (max-width: 360px) { .environment-meta { grid-template-columns: 1fr; } }
</style>