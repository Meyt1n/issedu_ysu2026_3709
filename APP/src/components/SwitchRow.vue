<script setup lang="ts">
const props = defineProps<{
  title: string
  description?: string
  modelValue: boolean
}>()

const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

function toggle(): void {
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <div class="switch-row">
    <span class="switch-text">
      <strong>{{ title }}</strong>
      <span v-if="description">{{ description }}</span>
    </span>
    <span class="switch-state" aria-hidden="true">{{ modelValue ? '开' : '关' }}</span>
    <button
      type="button"
      class="switch"
      role="switch"
      :aria-checked="modelValue"
      :aria-label="title"
      @click="toggle"
    ></button>
  </div>
</template>
