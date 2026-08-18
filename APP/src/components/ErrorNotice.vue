<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import type { ErrorPresentation } from '@/api/errors'

defineProps<{
  error: ErrorPresentation
}>()

const emit = defineEmits<{
  retry: []
}>()
</script>

<template>
  <aside class="error-notice notice" data-tone="error" role="alert">
    <span class="error-icon" aria-hidden="true"><AppIcon name="alert" :size="18" /></span>
    <span class="error-copy">
      <strong>请求未完成</strong>
      <span>{{ error.message }}</span>
    </span>
    <RouterLink v-if="error.action === 'settings'" class="error-action btn btn-quiet" to="/me">
      {{ error.actionLabel }}
    </RouterLink>
    <button v-else type="button" class="error-action btn btn-quiet" @click="emit('retry')">
      {{ error.actionLabel }}
    </button>
  </aside>
</template>

<style scoped>
.error-notice {
  display: flex;
  align-items: center;
  gap: 10px;
}

.error-icon {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--c-danger);
  color: #fff;
}

.error-copy {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 2px;
}

.error-copy strong { font-size: 0.9rem; }
.error-copy span { line-height: 1.45; }

.error-action {
  flex: 0 0 auto;
  min-height: 42px;
  padding-inline: 12px;
  font-size: 0.85rem;
}

@media (max-width: 380px) {
  .error-notice { align-items: flex-start; flex-wrap: wrap; }
  .error-copy { flex-basis: calc(100% - 42px); }
  .error-action { margin-left: 38px; }
}
</style>
