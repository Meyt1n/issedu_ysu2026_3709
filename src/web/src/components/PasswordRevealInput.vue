<script setup lang="ts">
import { ref } from 'vue'

import AppIcon from './AppIcon.vue'

const props = defineProps<{
  modelValue: string
  autocomplete?: string
  ariaLabel?: string
  ariaInvalid?: boolean | 'true' | 'false'
  inputmode?: 'text' | 'numeric' | 'tel' | 'email' | 'url'
  pattern?: string
  maxlength?: number
  minlength?: number
  required?: boolean
  disabled?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const visible = ref(false)
</script>

<template>
  <div class="password-reveal">
    <input
      :value="modelValue"
      :type="visible ? 'text' : 'password'"
      :autocomplete="autocomplete"
      :aria-label="ariaLabel"
      :aria-invalid="ariaInvalid"
      :inputmode="inputmode"
      :pattern="pattern"
      :maxlength="maxlength"
      :minlength="minlength"
      :required="required"
      :disabled="disabled"
      :placeholder="placeholder"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <button
      type="button"
      class="password-reveal-toggle"
      :aria-pressed="visible"
      :aria-label="visible ? '隐藏密码' : '显示密码'"
      :disabled="disabled"
      @click="visible = !visible"
    >
      <AppIcon :name="visible ? 'eye-off' : 'eye'" :size="16" />
    </button>
  </div>
</template>
