<script setup lang="ts">
defineProps<{
  /** 只在加载完成且结果发生变化时传入，避免重复播报页面正文。 */
  message: string
}>()
</script>

<template>
  <!--
    常驻 live region：荣耀屏幕朗读会遗漏由 v-if 临时插入的状态节点，
    因此只更新文字，不销毁播报容器。aria-atomic 保证状态切换时读完整句。
  -->
  <p class="list-status-announcer" role="status" aria-live="polite" aria-atomic="true" aria-relevant="text">
    {{ message }}
  </p>
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
