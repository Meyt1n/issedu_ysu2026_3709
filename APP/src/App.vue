<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppTabBar from '@/components/AppTabBar.vue'
import PrivacyNoticeSheet from '@/components/PrivacyNoticeSheet.vue'
import PwaUpdateNotice from '@/components/PwaUpdateNotice.vue'
import ToastHost from '@/components/ToastHost.vue'
import { useAuth } from '@/stores/auth'
import { usePrivacyNotice } from '@/stores/privacy'
import { useSession } from '@/stores/session'

const showPrivacyNotice = ref(false)
const { required: privacyNoticeRequired, acknowledge: acknowledgePrivacy } = usePrivacyNotice()
showPrivacyNotice.value = privacyNoticeRequired()

function onPrivacyAcknowledged(): void {
  const ok = acknowledgePrivacy()
  showPrivacyNotice.value = !ok
}

const route = useRoute()
const router = useRouter()
const { session } = useSession()
const { auth } = useAuth()

watch(
  () => auth.status,
  status => {
    if (status !== 'reauth-required') return
    if (session.dataMode !== 'live' || session.authMode !== 'real') return
    if (route.meta.requiresLiveAuth !== true) return
    void router.replace({ name: 'login', query: { redirect: route.fullPath } })
  },
)

watch(
  () => [session.mobileRole, route.fullPath] as const,
  ([mobileRole]) => {
    if (mobileRole !== 'member' || route.meta.adminOnly !== true) return
    void router.replace({ name: 'today' })
  },
)
</script>

<template>
  <div class="ambient-aurora" aria-hidden="true"><span /><span /><span /></div>
  <div class="ambient-fireflies" aria-hidden="true">
    <i /><i /><i /><i /><i /><i /><i /><i />
  </div>

  <a class="skip-link" href="#main">跳到主要内容</a>

  <RouterView v-slot="{ Component }">
    <Transition name="page" mode="out-in">
      <component :is="Component" />
    </Transition>
  </RouterView>
  <PwaUpdateNotice />
  <ToastHost />
  <AppTabBar />

  <PrivacyNoticeSheet
    v-if="showPrivacyNotice"
    @acknowledged="onPrivacyAcknowledged"
  />
</template>
