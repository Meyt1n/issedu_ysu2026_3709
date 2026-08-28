<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import type { ErrorPresentation } from '@/api/errors'

const props = withDefaults(
  defineProps<{
    error: ErrorPresentation
    /** 列表刷新期间锁定重试，避免同一请求被重复发起。 */
    busy?: boolean
    /** 部分数据保留时使用较温和的状态标题和色调。 */
    title?: string
    tone?: 'error' | 'warn'
  }>(),
  { busy: false, title: '请求未完成', tone: 'error' },
)

const emit = defineEmits<{
  retry: []
}>()
</script>

<template>
  <aside
    class="error-notice notice"
    :data-tone="props.tone"
    :role="props.tone === 'warn' ? 'status' : 'alert'"
    :aria-busy="props.busy || undefined"
  >
    <span class="error-icon" aria-hidden="true"><AppIcon name="alert" :size="18" /></span>
    <span class="error-copy">
      <strong>{{ props.title }}</strong>
      <span>{{ props.error.message }}</span>
      <span class="meta-line error-request-id">
        请求标识：{{ props.error.requestId ?? '回执信息不可用（服务端未返回请求 ID）' }}
      </span>
    </span>
    <RouterLink v-if="props.error.action === 'settings'" class="error-action btn btn-quiet" to="/me">
      {{ props.error.actionLabel }}
    </RouterLink>
    <button v-else type="button" class="error-action btn btn-quiet" :disabled="props.busy" @click="emit('retry')">
      {{ props.busy ? '正在重试…' : props.error.actionLabel }}
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

.error-notice[data-tone='warn'] .error-icon { background: var(--c-warn); }

.error-copy {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 2px;
}

.error-copy strong { font-size: 0.9rem; }
.error-request-id { font-size: 0.78rem; word-break: break-all; color: var(--c-ink-faint); }
.error-copy span { line-height: 1.45; }

.error-action {
  flex: 0 0 auto;
  min-height: var(--tap);
  padding-inline: 12px;
  font-size: 0.85rem;
}

@media (max-width: 380px) {
  .error-notice { align-items: flex-start; flex-wrap: wrap; }
  .error-copy { flex-basis: calc(100% - 42px); }
  .error-action { margin-left: 38px; }
}
</style>
