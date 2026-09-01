<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppTabBar from '@/components/AppTabBar.vue'
import PrivacyNoticeSheet from '@/components/PrivacyNoticeSheet.vue'
import PwaUpdateNotice from '@/components/PwaUpdateNotice.vue'
import ToastHost from '@/components/ToastHost.vue'
import {
  clearSpeechGuidance,
  useSpeakingIndicator,
  useSpeech,
  useSpeechGuidance,
} from '@/composables/useSpeech'
import { useAuth } from '@/stores/auth'
import { usePrivacyNotice } from '@/stores/privacy'
import { useSession } from '@/stores/session'

/** MOB-146：首次使用或隐私版本更新时展示告知；确认写入失败会再次展示。 */
const showPrivacyNotice = ref(false)
const { required: privacyNoticeRequired, acknowledge: acknowledgePrivacy } = usePrivacyNotice()
showPrivacyNotice.value = privacyNoticeRequired()

function onPrivacyAcknowledged(): void {
  const ok = acknowledgePrivacy()
  showPrivacyNotice.value = !ok
}

const speakingText = useSpeakingIndicator()
const speechGuidance = useSpeechGuidance()
const speech = useSpeech()

const route = useRoute()
const router = useRouter()
const { session } = useSession()
const { auth } = useAuth()

/**
 * 会话在使用过程中过期或被撤销时，立刻把用户带到登录页。
 * 只对需要联机数据的页面生效：设置、无障碍和求助页仍要可用。
 */
watch(
  () => auth.status,
  status => {
    if (status !== 'reauth-required') return
    if (session.dataMode !== 'live' || session.authMode !== 'real') return
    if (route.meta.requiresLiveAuth !== true) return
    void router.replace({ name: 'login', query: { redirect: route.fullPath } })
  },
)
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>

  <RouterView v-slot="{ Component }">
    <Transition name="page" mode="out-in">
      <component :is="Component" />
    </Transition>
  </RouterView>
  <PwaUpdateNotice />
  <ToastHost />

  <div v-if="speechGuidance" class="speech-guidance" role="status">
    <span>{{ speechGuidance }}</span>
    <button type="button" aria-label="关闭语音播报提示" @click="clearSpeechGuidance">知道了</button>
  </div>

  <!-- 语音播报可视指示：让听不清/关静音的用户也知道正在播报，可一键停止 -->
  <Transition name="speaking">
    <button
      v-if="speakingText"
      type="button"
      class="speaking-pill"
      aria-label="正在语音播报，点按停止"
      @click="speech.stop()"
    >
      <span class="speaking-wave" aria-hidden="true"><i></i><i></i><i></i></span>
      正在播报 · 点按停止
    </button>
  </Transition>

  <AppTabBar />

  <PrivacyNoticeSheet
    v-if="showPrivacyNotice"
    @acknowledged="onPrivacyAcknowledged"
  />
</template>

<style scoped>
.speech-guidance {
  position: fixed;
  left: 16px;
  right: 16px;
  /* 浮层要高于 4/5 项底部导航，避免 320px + 特大字号时遮挡入口。 */
  bottom: calc(144px + var(--hct-safe-area-bottom));
  z-index: 31;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  color: var(--c-ink);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-float);
  font-size: 0.86rem;
  line-height: 1.45;
}
.speech-guidance span { flex: 1; }
.speech-guidance button {
  flex: 0 0 auto;
  min-height: 44px;
  padding: 0 10px;
  color: var(--c-brand);
  background: transparent;
  border: 1px solid currentColor;
  border-radius: 10px;
  font: inherit;
  font-weight: 700;
}
html[data-elder='on'] .speech-guidance button { min-height: 58px; }
html[data-contrast='high'] .speech-guidance { background: #fff; border: 2px solid #000; box-shadow: none; }
.speaking-pill {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: calc(144px + var(--hct-safe-area-bottom));
  z-index: 30;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  border: 1px solid var(--glass-border);
  border-radius: var(--r-pill);
  background: var(--glass-bg);
  -webkit-backdrop-filter: blur(16px) saturate(1.5);
  backdrop-filter: blur(16px) saturate(1.5);
  color: var(--c-ink);
  font-weight: 700;
  font-size: 0.84rem;
  min-height: var(--tap);
  padding: 9px 16px;
  box-shadow: var(--shadow-float), inset 0 1px 0 var(--hilite);
  cursor: pointer;
}
.speaking-wave { display: inline-flex; align-items: flex-end; gap: 2.5px; height: 14px; }
.speaking-wave i {
  width: 3px;
  border-radius: 2px;
  background: var(--c-brand);
  animation: speak-bar 0.9s ease-in-out infinite alternate;
}
.speaking-wave i:nth-child(1) { height: 6px; }
.speaking-wave i:nth-child(2) { height: 13px; animation-delay: 0.15s; }
.speaking-wave i:nth-child(3) { height: 9px; animation-delay: 0.3s; }
@keyframes speak-bar {
  from { transform: scaleY(0.45); }
  to { transform: scaleY(1); }
}
html[data-elder='on'] .speaking-pill { min-height: var(--tap); }
html[data-elder='on'] .speech-guidance button { min-height: var(--tap); }

html[data-contrast='high'] .speech-guidance {
  position: fixed;
  left: 16px;
  right: 16px;
  bottom: calc(144px + var(--hct-safe-area-bottom));
  z-index: 31;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  color: var(--c-ink);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-float);
  font-size: 0.86rem;
  line-height: 1.45;
}
.speech-guidance span { flex: 1; }
.speech-guidance button {
  flex: 0 0 auto;
  min-height: 44px;
  padding: 0 10px;
  color: var(--c-brand);
  background: transparent;
  border: 1px solid currentColor;
  border-radius: 10px;
  font: inherit;
  font-weight: 700;
}
html[data-elder='on'] .speech-guidance button { min-height: 58px; }
html[data-contrast='high'] .speech-guidance { background: #fff; border: 2px solid #000; box-shadow: none; }
.speaking-pill { background: #fff; border: 2px solid #000; box-shadow: none; }

.speaking-enter-active,
.speaking-leave-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.speaking-enter-from,
.speaking-leave-to { opacity: 0; transform: translateX(-50%) translateY(10px); }
</style>
