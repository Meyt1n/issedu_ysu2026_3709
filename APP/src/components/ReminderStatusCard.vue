<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import type { ReminderSyncResult } from '@/notifications/reminderScheduler'

defineProps<{ state: ReminderSyncResult }>()
</script>

<template>
  <section class="card reminder-status" aria-labelledby="reminder-status-title">
    <div class="reminder-heading">
      <span class="icon-disc" data-tone="info" aria-hidden="true"><AppIcon name="bell" :size="20" /></span>
      <div>
        <h2 id="reminder-status-title">计划提醒</h2>
        <p class="meta-line">通知不会显示成员姓名、药名、风险详情或健康正文。</p>
      </div>
    </div>
    <p class="meta-line" role="status">{{ state.reason }}</p>
  </section>
</template>

<style scoped>
.reminder-status { margin-top: 10px; display: grid; gap: 10px; }
.reminder-heading { display: flex; align-items: flex-start; gap: 10px; }
h2 { margin: 0; font-size: 1rem; }
</style>
