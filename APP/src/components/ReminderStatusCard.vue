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
    <details class="reminder-help">
      <summary>如何允许 Android 计划提醒</summary>
      <ol>
        <li>在系统设置中打开“通知 → 家健镜 → 允许通知”。</li>
        <li>在电池或应用启动设置中允许后台活动，并关闭本应用的电池优化。</li>
        <li>如果 ROM 提供“自启动”或“后台弹出”开关，也请为家健镜开启。</li>
        <li>检查锁屏通知和勿扰模式；锁屏通知只会显示“请打开应用查看今日安排”。</li>
      </ol>
      <p class="meta-line">不同 Android/ROM 的菜单名称可能不同；改完系统设置后，请重新打开应用同步计划。应用不会把未确认的本地通知说成已送达。</p>
    </details>
  </section>
</template>

<style scoped>
.reminder-status { margin-top: 10px; display: grid; gap: 10px; }
.reminder-heading { display: flex; align-items: flex-start; gap: 10px; }
h2 { margin: 0; font-size: 1rem; }
.reminder-help { border-top: 1px solid var(--line); padding-top: 8px; }
.reminder-help summary { cursor: pointer; font-weight: 700; }
.reminder-help ol { margin: 8px 0; padding-left: 22px; }
.reminder-help li + li { margin-top: 5px; }
</style>
