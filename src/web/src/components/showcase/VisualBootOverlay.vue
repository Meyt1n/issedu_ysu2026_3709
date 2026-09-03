<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { CapabilityResponse } from '../../api/types'
import { bootPhaseState, SHOWCASE_BOOT_PHASES } from '../../ui/showcase'

const props = defineProps<{
  visible: boolean
  capabilities?: CapabilityResponse | null
}>()

const emit = defineEmits<{
  complete: []
}>()

const activeIndex = ref(0)
let phaseTimer: ReturnType<typeof setInterval> | null = null
let finishTimer: ReturnType<typeof setTimeout> | null = null

function stopTimers(): void {
  if (phaseTimer) clearInterval(phaseTimer)
  if (finishTimer) clearTimeout(finishTimer)
  phaseTimer = null
  finishTimer = null
}

function finish(): void {
  stopTimers()
  emit('complete')
}

function start(): void {
  stopTimers()
  activeIndex.value = 0
  phaseTimer = setInterval(() => {
    if (activeIndex.value < SHOWCASE_BOOT_PHASES.length - 1) {
      activeIndex.value += 1
      return
    }
    if (!finishTimer) finishTimer = setTimeout(finish, 680)
  }, 460)
}

function onKeydown(event: KeyboardEvent): void {
  if (props.visible && event.key === 'Escape') {
    event.preventDefault()
    finish()
  }
}

function phaseStatus(key: string, index: number): string {
  if (index > activeIndex.value) return '等待'
  if (key === 'local') return props.capabilities?.available.includes('llm') ? '在线' : '可选'
  if (key === 'graph') return props.capabilities ? '在线' : '本地'
  if (key === 'privacy') return '活跃'
  return index < activeIndex.value ? '完成' : '运行'
}

watch(() => props.visible, visible => {
  if (visible) start()
  else stopTimers()
}, { immediate: true })

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
onBeforeUnmount(stopTimers)
</script>

<template>
  <Teleport to="body">
    <Transition name="boot-fade">
      <div
        v-if="visible"
        class="warm-boot"
        role="status"
        aria-live="polite"
        aria-label="家健镜系统启动"
      >
        <div class="warm-boot-overlay" aria-hidden="true" />

        <div class="warm-boot-core">
          <div class="warm-boot-emblem" aria-hidden="true">
            <svg viewBox="0 0 48 48" width="48" height="48" fill="none">
              <path
                d="M8 20.8 24 12l16 8.8"
                stroke="currentColor"
                stroke-width="2.4"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <path
                d="M12 17.6V30a1.6 1.6 0 0 0 1.6 1.6h20.8A1.6 1.6 0 0 0 36 30V17.6"
                stroke="currentColor"
                stroke-width="2.4"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <path
                d="M24 26.4s-4.16-2.72-4.16-5.44c0-1.44 1.12-2.56 2.4-2.56.8 0 1.44.32 1.76.96.32-.64.96-.96 1.76-.96 1.28 0 2.4 1.12 2.4 2.56 0 2.72-4.16 5.44-4.16 5.44Z"
                stroke="currentColor"
                stroke-width="2.4"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </div>

          <p class="warm-boot-kicker">HomeCare Twin</p>
          <h2>家庭健康空间</h2>
          <p class="warm-boot-subtitle">正在连接本地照护系统</p>

          <ol class="warm-boot-phases" aria-live="polite">
            <li
              v-for="(phase, index) in SHOWCASE_BOOT_PHASES"
              :key="phase.key"
              class="warm-boot-phase"
              :class="bootPhaseState(index, activeIndex)"
            >
              <span class="warm-boot-marker">
                <svg v-if="index < activeIndex" viewBox="0 0 16 16" width="16" height="16">
                  <path
                    d="M13 4 6 11 3 8"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    fill="none"
                  />
                </svg>
                <span v-else-if="index === activeIndex" class="marker-pulse" />
                <span v-else class="marker-wait" />
              </span>
              <span class="warm-boot-phase-copy">
                <strong>{{ phase.label }}</strong>
                <small>{{ phase.hint }}</small>
              </span>
              <span class="warm-boot-phase-status">
                {{ phaseStatus(phase.key, index) }}
              </span>
            </li>
          </ol>

          <div class="warm-boot-progress" aria-hidden="true">
            <span :style="{ width: `${((activeIndex + 1) / SHOWCASE_BOOT_PHASES.length) * 100}%` }" />
          </div>

          <button type="button" class="warm-boot-skip" @click="finish">
            跳过 <kbd>Esc</kbd>
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.warm-boot {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  /* 纯 CSS 温暖背景：纸色基底 + 柔和晨光径向渐变，替代已移除的照片背景。 */
  background:
    radial-gradient(circle at 18% 12%, rgba(244, 232, 200, 0.85) 0%, transparent 52%),
    radial-gradient(circle at 84% 88%, rgba(227, 236, 231, 0.9) 0%, transparent 55%),
    var(--paper, #f6f1e6);
}

.warm-boot-overlay {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse at center, transparent 55%, rgba(94, 71, 42, 0.08) 100%),
    radial-gradient(
      ellipse at center,
      rgba(255, 252, 243, 0.42) 0%,
      rgba(255, 252, 243, 0.62) 50%,
      rgba(255, 252, 243, 0.74) 100%
    );
  z-index: 1;
}

.warm-boot-core {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 520px;
  padding: 48px 40px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
}

.warm-boot-emblem {
  width: 64px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--pine, #38665a);
  animation: emblem-appear 620ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

.warm-boot-kicker {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 500;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-soft, #6d6659);
  opacity: 0;
  animation: text-fade-up 480ms ease 180ms both;
}

.warm-boot h2 {
  margin: 0;
  font-size: 2.2rem;
  font-weight: 600;
  color: var(--ink, #3f3a31);
  font-family: Georgia, 'Times New Roman', serif;
  opacity: 0;
  animation: text-fade-up 480ms ease 280ms both;
}

.warm-boot-subtitle {
  margin: 0;
  font-size: 1.05rem;
  color: var(--ink-soft, #6d6659);
  opacity: 0;
  animation: text-fade-up 480ms ease 380ms both;
}

.warm-boot-phases {
  width: 100%;
  margin: 24px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
  opacity: 0;
  animation: text-fade-up 480ms ease 480ms both;
}

.warm-boot-phase {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(190, 167, 125, 0.24);
  text-align: left;
  transition: background 280ms ease, border-color 280ms ease, transform 280ms ease;
}

.warm-boot-phase.active {
  background: rgba(238, 247, 239, 0.84);
  border-color: rgba(52, 104, 88, 0.32);
  transform: translateX(3px);
}

.warm-boot-phase.done {
  background: rgba(255, 255, 255, 0.4);
  opacity: 0.7;
}

.warm-boot-marker {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.8);
  border: 2px solid rgba(190, 167, 125, 0.3);
  color: var(--pine, #38665a);
}

.warm-boot-phase.active .warm-boot-marker {
  border-color: var(--pine, #38665a);
  background: rgba(238, 247, 239, 0.9);
}

.warm-boot-phase.done .warm-boot-marker {
  border-color: var(--pine, #38665a);
  background: var(--pine, #38665a);
  color: white;
}

.marker-pulse {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--pine, #38665a);
  animation: marker-pulse-anim 1.2s ease-in-out infinite;
}

.marker-wait {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(190, 167, 125, 0.3);
}

.warm-boot-phase-copy {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.warm-boot-phase-copy strong {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--ink, #3f3a31);
}

.warm-boot-phase-copy small {
  font-size: 0.82rem;
  color: var(--ink-soft, #6d6659);
  opacity: 0.88;
}

.warm-boot-phase-status {
  flex-shrink: 0;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--pine-deep, #2a4d42);
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(238, 247, 239, 0.6);
}

.warm-boot-progress {
  width: 100%;
  height: 4px;
  background: rgba(190, 167, 125, 0.2);
  border-radius: 999px;
  overflow: hidden;
  margin-top: 8px;
}

.warm-boot-progress span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--pine, #38665a), var(--gold, #c26744));
  border-radius: 999px;
  transition: width 380ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

.warm-boot-skip {
  margin-top: 16px;
  padding: 10px 24px;
  border: 1px solid rgba(190, 167, 125, 0.28);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
  color: var(--ink-soft, #6d6659);
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 220ms ease, border-color 220ms ease, transform 220ms ease;
}

.warm-boot-skip:hover {
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(190, 167, 125, 0.42);
  transform: translateY(-1px);
}

.warm-boot-skip kbd {
  margin-left: 6px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(109, 102, 89, 0.12);
  font-family: ui-monospace, monospace;
  font-size: 0.82rem;
}

@keyframes emblem-appear {
  from {
    opacity: 0;
    transform: scale(0.7) translateY(20px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

@keyframes text-fade-up {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes marker-pulse-anim {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.3);
    opacity: 0.7;
  }
}

.boot-fade-enter-active,
.boot-fade-leave-active {
  transition: opacity 420ms ease;
}

.boot-fade-enter-from,
.boot-fade-leave-to {
  opacity: 0;
}

@media (max-width: 640px) {
  .warm-boot-core {
    padding: 32px 24px;
    gap: 16px;
  }

  .warm-boot h2 {
    font-size: 1.8rem;
  }

  .warm-boot-phase {
    padding: 12px 14px;
    gap: 12px;
  }

  .warm-boot-marker {
    width: 24px;
    height: 24px;
  }
}
</style>
