<script setup lang="ts">
import AppIcon, { type IconName } from '@/components/AppIcon.vue'

withDefaults(
  defineProps<{
    icon?: IconName
    title: string
    hint?: string
  }>(),
  { icon: 'check', hint: '' },
)
</script>

<template>
  <div class="empty-state">
    <span class="empty-icon" aria-hidden="true">
      <AppIcon :name="icon" :size="26" />
    </span>
    <p>{{ title }}</p>
    <p v-if="hint" class="meta-line">{{ hint }}</p>
  </div>
</template>
