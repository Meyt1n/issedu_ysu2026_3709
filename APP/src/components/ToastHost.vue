<script setup lang="ts">
import AppIcon, { type IconName } from '@/components/AppIcon.vue'
import { dismissToast, useToasts, type ToastTone } from '@/composables/useToast'

const { toasts } = useToasts()

const ICONS: Record<ToastTone, IconName> = {
  success: 'check',
  error: 'alert',
  info: 'sound',
}
</script>

<template>
  <div class="toast-host" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <button
        v-for="toast in toasts"
        :key="toast.id"
        type="button"
        class="toast"
        :data-tone="toast.tone"
        @click="dismissToast(toast.id)"
      >
        <span class="toast-icon" aria-hidden="true">
          <AppIcon :name="ICONS[toast.tone]" :size="16" />
        </span>
        {{ toast.text }}
      </button>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: calc(12px + env(safe-area-inset-top));
  left: 16px;
  right: 16px;
  z-index: 60;
  display: grid;
  justify-items: center;
  gap: 8px;
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  max-width: min(100%, 480px);
  border: 1px solid var(--glass-border);
  border-radius: var(--r-pill);
  background: var(--glass-bg);
  -webkit-backdrop-filter: blur(18px) saturate(1.5);
  backdrop-filter: blur(18px) saturate(1.5);
  color: var(--c-ink);
  font-weight: 700;
  font-size: 0.9rem;
  padding: 10px 16px;
  box-shadow: var(--shadow-float), inset 0 1px 0 var(--hilite);
  cursor: pointer;
  text-align: left;
}

.toast-icon {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--c-calm);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.toast[data-tone='error'] .toast-icon { background: var(--c-danger); }
.toast[data-tone='info'] .toast-icon { background: var(--c-info); }

html[data-contrast='high'] .toast {
  background: #fff;
  border: 2px solid #000;
  box-shadow: none;
  -webkit-backdrop-filter: none;
  backdrop-filter: none;
}

.toast-enter-active {
  transition: opacity 0.3s var(--ease), transform 0.3s var(--ease-spring);
}
.toast-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateY(-16px) scale(0.92); }
.toast-leave-to { opacity: 0; transform: translateY(-8px) scale(0.96); }
</style>
