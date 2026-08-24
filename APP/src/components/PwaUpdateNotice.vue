<script setup lang="ts">
/**
 * MOB-151：全局更新提示。新版本只在用户确认后接管（sw.js 等待
 * SKIP_WAITING），提示可关闭、可读屏，不阻断求助入口。
 */
import {
  applyPendingUpdate,
  currentContainer,
  currentRegistration,
  updateApplying,
  updateReady,
} from '@/stores/pwa'
import { tapFeedback } from '@/utils/haptics'

function dismiss(): void {
  tapFeedback()
  updateReady.value = false
}

function onApply(): void {
  tapFeedback()
  const container = currentContainer()
  if (!container) return
  applyPendingUpdate(container, currentRegistration())
}
</script>

<template>
  <div v-if="updateReady" class="pwa-update-notice" role="alert" aria-labelledby="pwa-update-title" data-tone="info">
    <p id="pwa-update-title" class="pwa-update-title">发现新版本</p>
    <p class="pwa-update-desc">
      刷新后生效；正在提交的任务不会被中途切换，求助入口保持可用。
      更新后在“我的”页可查看新版本号与构建提交。
    </p>
    <div class="pwa-update-actions">
      <button type="button" :disabled="updateApplying" @click="onApply">
        {{ updateApplying ? '正在更新…' : '立即刷新更新' }}
      </button>
      <button type="button" class="secondary" :disabled="updateApplying" @click="dismiss">稍后</button>
    </div>
  </div>
</template>

<style scoped>
.pwa-update-notice {
  position: fixed;
  inset-inline: 12px;
  bottom: calc(var(--tabbar-height, 64px) + 12px);
  z-index: 60;
  max-width: 480px;
  margin-inline: auto;
  padding: 12px 14px;
  border-radius: 14px;
  background: #fffdf7;
  border: 1px solid #2f6d5a;
  box-shadow: 0 10px 28px rgba(34, 82, 63, 0.22);
}

.pwa-update-title {
  margin: 0 0 4px;
  font-weight: 700;
  color: #22523f;
}

.pwa-update-desc {
  margin: 0 0 10px;
  font-size: 0.9rem;
  line-height: 1.5;
  color: #33413a;
}

.pwa-update-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.pwa-update-actions button {
  border: 1px solid #2f6d5a;
  background: #2f6d5a;
  color: #fff;
  border-radius: 10px;
  padding: 8px 14px;
  font-size: 0.9rem;
}

.pwa-update-actions button.secondary {
  background: transparent;
  color: #2f6d5a;
}

.pwa-update-actions button:disabled {
  opacity: 0.6;
}
</style>
