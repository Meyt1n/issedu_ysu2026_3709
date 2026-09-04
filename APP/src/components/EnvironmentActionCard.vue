<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import type { EnvironmentActionState } from '@/data/types'

defineProps<{ state: EnvironmentActionState }>()
</script>

<template>
  <section class="card environment-card" aria-labelledby="environment-title">
    <div class="environment-heading">
      <span class="icon-disc" data-tone="info" aria-hidden="true"><AppIcon name="heart" :size="20" /></span>
      <h2 id="environment-title">天气</h2>
    </div>
    <template v-if="state.availability === 'AVAILABLE' && state.card">
      <p class="environment-action">{{ state.card.action }}</p>
    </template>
    <p v-else class="meta-line" role="status">暂无天气信息</p>
  </section>
</template>

<style scoped>
.environment-card { margin-top: 10px; display: grid; gap: 12px; }
.environment-heading { display: flex; align-items: center; gap: 10px; }
.environment-heading h2 { margin: 0; font-size: 1rem; }
.environment-action { margin: 0; font-weight: 750; line-height: 1.5; }
</style>
