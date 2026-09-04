<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useSession } from '@/stores/session'
import { tapFeedback } from '@/utils/haptics'
import { detectPhoneCapability, getHelpDialHref, type HelpCallTarget } from '@/utils/help'

const { session } = useSession()
const online = ref(typeof navigator === 'undefined' ? true : navigator.onLine)
const phoneCapability = computed(() =>
  detectPhoneCapability(typeof navigator === 'undefined' ? '' : navigator.userAgent),
)
const offlineNotice = computed(() => !online.value)

function updateOnlineState(): void {
  online.value = navigator.onLine
}

onMounted(() => {
  window.addEventListener('online', updateOnlineState)
  window.addEventListener('offline', updateOnlineState)
})
onBeforeUnmount(() => {
  window.removeEventListener('online', updateOnlineState)
  window.removeEventListener('offline', updateOnlineState)
})
const phoneHref = computed(() => getHelpDialHref('caregiver', session.caregiverPhone))

function callTarget(target: HelpCallTarget): void {
  const href = getHelpDialHref(target, session.caregiverPhone)
  if (!href) return
  tapFeedback([12, 60, 18])
  window.location.href = href
}

</script>

<template>
  <main id="main" class="screen">
        <p v-if="offlineNotice" class="notice" data-tone="warn" role="status">
      当前处于离线状态：静态求助说明、120 和已保存联系人仍可用；动态风险提醒不会从缓存恢复。
    </p>
    <p v-if="phoneCapability === 'unavailable'" class="notice" data-tone="warn" role="status">
      当前设备可能无法直接拨号。点击后会尝试交给系统处理；若未打开电话应用，请使用身边可用电话拨打 120 或联系家人。
    </p>

    <header class="screen-header">
      <p class="eyebrow">紧急情况</p>
      <h1>求助</h1>
      <p class="screen-subtitle">如果感到严重不适，请立即拨打急救电话或联系家人，不要等待应用提示。</p>
    </header>

    <button
      type="button"
      class="btn btn-lg btn-block emergency-btn"
      @click="callTarget('emergency')"
    >
      <AppIcon name="phone" :size="24" />
      拨打急救电话 120
    </button>
    <p class="meta-line">请在紧急情况下拨打。</p>

    <button
      v-if="phoneHref"
      type="button"
      class="btn btn-lg btn-block"
      @click="callTarget('caregiver')"
    >
      <AppIcon name="family" :size="24" />
      联系家人{{ session.caregiverName ? `：${session.caregiverName}` : '' }}（{{ session.caregiverPhone }}）
    </button>
    <div v-else class="card">
      <p class="notice" data-tone="warn">还没有设置紧急联系人。</p>
      <RouterLink class="btn btn-quiet btn-block" to="/me">去「我的」页设置家人电话</RouterLink>
    </div>

    <section class="card">
      <h2>拨号前可以准备什么</h2>
      <ul class="divided-list">
        <li>说清楚人在哪里（小区、楼栋、门牌号）。</li>
        <li>说明谁不舒服、大概什么症状、从什么时候开始。</li>
        <li>如方便，告知正在服用的药物（可在“家人”页查看获授权的用药记录）。</li>
      </ul>
    </section>

    <footer class="disclaimer">
      家健镜不提供在线问诊或购药入口；紧急情况请始终以医生和急救服务的判断为准。
    </footer>

  </main>
</template>

<style scoped>
.emergency-btn {
  background: linear-gradient(135deg, #de7263 0%, #d2604f 55%, #b84c3b 100%);
  color: #fff;
  box-shadow: 0 12px 26px -12px rgba(210, 96, 79, 0.65);
  animation: sos-pulse 2.6s var(--ease) infinite;
}
.emergency-btn:hover { filter: brightness(1.08); }
html[data-contrast='high'] .emergency-btn {
  background: var(--c-danger);
  box-shadow: none;
  border: 2px solid #000;
  animation: none;
}
</style>
