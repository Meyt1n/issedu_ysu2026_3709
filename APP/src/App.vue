<script setup lang="ts">
import AppTabBar from '@/components/AppTabBar.vue'
import ToastHost from '@/components/ToastHost.vue'
import { useSpeakingIndicator, useSpeech } from '@/composables/useSpeech'

const speakingText = useSpeakingIndicator()
const speech = useSpeech()
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>

  <!-- 氛围背景：AI 生成水彩底图 + 柔光色斑 + 线条装饰，纯装饰层，高对比模式自动隐藏 -->
  <div class="bg-scene" aria-hidden="true">
    <img class="bg-art bg-art--light" src="/bg/ambient-light.jpg" alt="" loading="eager" decoding="async" />
    <img class="bg-art bg-art--dark" src="/bg/ambient-dark.jpg" alt="" loading="eager" decoding="async" />
    <span class="blob blob-a"></span>
    <span class="blob blob-b"></span>
    <span class="blob blob-c"></span>
    <span class="ring-deco ring-deco--a"></span>
    <span class="ring-deco ring-deco--b"></span>
    <svg class="leaf-deco leaf-deco--a" width="88" height="88" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 21c0-9.5 7.5-17 17-17 0 9.5-7.5 17-17 17z" />
      <path d="M5 19C9.5 14.5 14 10 18.5 5.5" />
    </svg>
    <svg class="leaf-deco leaf-deco--b" width="88" height="88" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 21c0-9.5 7.5-17 17-17 0 9.5-7.5 17-17 17z" />
      <path d="M5 19C9.5 14.5 14 10 18.5 5.5" />
    </svg>
  </div>


  <RouterView v-slot="{ Component }">
    <Transition name="page" mode="out-in">
      <component :is="Component" />
    </Transition>
  </RouterView>
  <ToastHost />

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
</template>

<style scoped>
.speaking-pill {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: calc(96px + env(safe-area-inset-bottom));
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
html[data-contrast='high'] .speaking-pill { background: #fff; border: 2px solid #000; box-shadow: none; }

.speaking-enter-active,
.speaking-leave-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.speaking-enter-from,
.speaking-leave-to { opacity: 0; transform: translateX(-50%) translateY(10px); }
</style>
