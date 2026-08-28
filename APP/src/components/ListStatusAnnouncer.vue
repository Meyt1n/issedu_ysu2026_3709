<script setup lang="ts">
defineProps<{
  /** 只在加载完成且结果发生变化时传入，避免重复播报页面正文。 */
  message: string
}>()
</script>

<template>
  <p v-if="message" class="list-status-announcer" role="status" aria-live="polite">{{ message }}</p>
</template>

<style scoped>
.list-status-announcer {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>
