<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 42 })
</script>

<template>
  <img class="brand-logo" src="/icons/icon.svg" alt="家健镜" :width="size" :height="size" />
</template>

<style scoped>
.brand-logo {
  display: block;
  flex: 0 0 auto;
  border-radius: 22%;
}
</style>
