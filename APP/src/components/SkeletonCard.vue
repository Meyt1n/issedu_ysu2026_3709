<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 是否显示左侧圆形占位（头像/图标位） */
    disc?: boolean
  }>(),
  { disc: true },
)
</script>

<template>
  <div class="skeleton-card" aria-hidden="true">
    <span v-if="disc" class="sk sk-disc"></span>
    <span class="sk-lines">
      <span class="sk sk-line" style="width: 62%"></span>
      <span class="sk sk-line" style="width: 88%"></span>
      <span class="sk sk-line" style="width: 40%"></span>
    </span>
  </div>
</template>

<style scoped>
.skeleton-card {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  background: var(--c-surface);
  -webkit-backdrop-filter: var(--glass-blur);
  backdrop-filter: var(--glass-blur);
  border: 1px solid var(--c-line);
  border-radius: var(--r-card);
  padding: 18px;
  position: relative;
  overflow: hidden;
}
.skeleton-card::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, transparent 32%, var(--sheen) 50%, transparent 68%);
  transform: translateX(-100%);
  animation: shimmer 1.5s ease-in-out infinite;
}
@keyframes shimmer {
  to { transform: translateX(100%); }
}

.sk { display: block; background: var(--well-bg); border-radius: 8px; }
.sk-disc { flex: 0 0 auto; width: 44px; height: 44px; border-radius: 38%; }
.sk-lines { flex: 1; display: grid; gap: 9px; padding-top: 3px; }
.sk-line { height: 12px; }

html[data-contrast='high'] .skeleton-card { border: 2px solid #000; }
html[data-contrast='high'] .sk { background: #e5e5e5; }
</style>
