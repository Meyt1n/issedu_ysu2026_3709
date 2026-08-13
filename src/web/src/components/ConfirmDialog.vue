<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

import { confirmState, settleConfirm } from '../ui/confirm'
import AppIcon from './AppIcon.vue'

function onKeydown(event: KeyboardEvent): void {
  if (!confirmState.open) return
  if (event.key === 'Escape') settleConfirm(false)
  if (event.key === 'Enter') settleConfirm(true)
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="confirmState.open"
        class="modal-backdrop"
        role="alertdialog"
        aria-modal="true"
        :aria-label="confirmState.options.title"
        @click.self="settleConfirm(false)"
      >
        <div class="modal-card">
          <span class="modal-icon" :class="confirmState.options.tone">
            <AppIcon :name="confirmState.options.tone === 'danger' ? 'alert' : 'info'" :size="22" />
          </span>
          <h3 class="modal-title">{{ confirmState.options.title }}</h3>
          <p class="modal-message">{{ confirmState.options.message }}</p>
          <div class="modal-actions">
            <button type="button" class="btn btn-ghost" @click="settleConfirm(false)">
              {{ confirmState.options.cancelText }}
            </button>
            <button
              type="button"
              class="btn"
              :class="confirmState.options.tone === 'danger' ? 'btn-danger modal-danger-solid' : 'btn-primary'"
              @click="settleConfirm(true)"
            >
              {{ confirmState.options.confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
