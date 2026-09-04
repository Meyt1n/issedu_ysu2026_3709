<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { CapabilityResponse } from '../../api/types'
import CompanionPet from '../CompanionPet.vue'
import { bootPhaseState, SHOWCASE_BOOT_PHASES } from '../../ui/showcase'

const props = defineProps<{
  visible: boolean
  capabilities?: CapabilityResponse | null
}>()

const emit = defineEmits<{
  complete: []
}>()

const activeIndex = ref(0)
const progressValue = computed(() => ((activeIndex.value + 1) / SHOWCASE_BOOT_PHASES.length) * 100)
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
    if (!finishTimer) finishTimer = setTimeout(finish, 900)
  }, 520)
}

function onKeydown(event: KeyboardEvent): void {
  if (props.visible && event.key === 'Escape') {
    event.preventDefault()
    finish()
  }
}

function phaseStatus(key: string, index: number): string {
  if (index > activeIndex.value) return '准备中'
  if (key === 'local') return props.capabilities?.available.includes('llm') ? '在线' : '本地'
  if (key === 'graph') return props.capabilities ? '在线' : '本地'
  if (key === 'privacy') return '活跃'
  if (key === 'ready') return '运行'
  return index < activeIndex.value ? '完成' : '启动'
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
        aria-label="家健镜家庭健康空间正在启动"
      >
        <div class="warm-boot-paper" aria-hidden="true" />
        <div class="warm-boot-wash warm-boot-wash-left" aria-hidden="true" />
        <div class="warm-boot-wash warm-boot-wash-right" aria-hidden="true" />

        <svg class="warm-boot-plant warm-boot-plant-left" viewBox="0 0 280 560" aria-hidden="true">
          <path d="M43 555C65 430 83 300 130 174 153 113 186 65 239 20" />
          <path d="M111 228c-53-10-88 8-105 49 44 9 81-6 105-49Z" />
          <path d="M145 149c-25-42-62-59-106-46 18 38 54 54 106 46Z" />
          <path d="M168 103c8-46 34-75 79-85-3 42-29 70-79 85Z" />
          <path d="M81 341c-40-31-80-32-119-3 34 28 74 29 119 3Z" />
          <path d="M69 409c14-43 44-66 91-68-10 41-40 64-91 68Z" />
        </svg>

        <svg class="warm-boot-plant warm-boot-plant-right" viewBox="0 0 300 590" aria-hidden="true">
          <path d="M270 588C247 440 224 328 173 210 142 138 105 83 47 23" />
          <path d="M196 260c51-15 91-1 119 42-47 14-87 0-119-42Z" />
          <path d="M161 181c21-47 57-68 107-61-15 43-51 64-107 61Z" />
          <path d="M130 133c-10-45-39-73-86-82 6 43 35 70 86 82Z" />
          <path d="M233 401c37-34 77-39 120-15-31 32-71 37-120 15Z" />
          <path d="M243 470c-17-42-49-62-95-60 13 40 45 60 95 60Z" />
        </svg>

        <span class="warm-boot-leaf leaf-one" aria-hidden="true" />
        <span class="warm-boot-leaf leaf-two" aria-hidden="true" />
        <span class="warm-boot-leaf leaf-three" aria-hidden="true" />
        <span class="warm-boot-spark spark-one" aria-hidden="true" />
        <span class="warm-boot-spark spark-two" aria-hidden="true" />

        <main class="warm-boot-stage">
          <section class="warm-boot-core">
            <header class="warm-boot-heading">
              <div class="warm-boot-emblem" aria-hidden="true">
                <svg viewBox="0 0 64 64" fill="none">
                  <path d="M12 29 32 14l20 15" />
                  <path d="M17 25v22c0 2 1.6 3.5 3.5 3.5h23c2 0 3.5-1.5 3.5-3.5V25" />
                  <path class="emblem-heart" d="M32 42s-8-4.9-8-10.2c0-2.8 2.1-4.8 4.7-4.8 1.5 0 2.7.6 3.3 1.8.7-1.2 1.8-1.8 3.3-1.8 2.6 0 4.7 2 4.7 4.8C40 37.1 32 42 32 42Z" />
                </svg>
              </div>
              <p class="warm-boot-kicker"><i /> HOMECARE TWIN <i /></p>
              <h2>家庭健康空间</h2>
              <p class="warm-boot-subtitle">正在连接本地照护系统</p>
              <span class="warm-boot-heading-sprout" aria-hidden="true">⌁</span>
            </header>

            <ol class="warm-boot-phases">
              <li
                v-for="(phase, index) in SHOWCASE_BOOT_PHASES"
                :key="phase.key"
                class="warm-boot-phase"
                :class="[bootPhaseState(index, activeIndex), `phase-${phase.key}`]"
              >
                <span class="warm-boot-marker" aria-hidden="true">
                  <svg v-if="index < activeIndex" viewBox="0 0 20 20">
                    <path d="m16 5-8.4 9L4 10.3" />
                  </svg>
                  <svg v-else-if="phase.key === 'privacy' && index === activeIndex" viewBox="0 0 20 20">
                    <path d="M10 2.5 16 5v4.2c0 3.8-2.5 6.5-6 8.3-3.5-1.8-6-4.5-6-8.3V5l6-2.5Z" />
                    <path d="m7.3 10 1.7 1.7 3.8-4" />
                  </svg>
                  <span v-else-if="index === activeIndex" class="marker-pulse" />
                  <span v-else class="marker-wait" />
                </span>

                <span class="warm-boot-phase-copy">
                  <strong>{{ phase.label }}</strong>
                  <small>{{ phase.hint }}</small>
                </span>
                <span class="warm-boot-phase-status">{{ phaseStatus(phase.key, index) }}</span>
              </li>
            </ol>

            <div
              class="warm-boot-progress"
              role="progressbar"
              aria-label="家庭健康空间启动进度"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-valuenow="Math.round(progressValue)"
            >
              <span :style="{ width: `${progressValue}%` }"><i aria-hidden="true" /></span>
            </div>

            <button type="button" class="warm-boot-skip" @click="finish">
              跳过 <kbd>Esc</kbd>
            </button>
          </section>

          <aside class="warm-boot-companion" aria-hidden="true">
            <div class="companion-aura aura-one" />
            <div class="companion-aura aura-two" />
            <div class="companion-orbit orbit-one" />
            <div class="companion-orbit orbit-two" />
            <span class="companion-glint glint-one" />
            <span class="companion-glint glint-two" />
            <span class="companion-glint glint-three" />

            <CompanionPet
              class="sprout-friend"
              state="loading"
              size="large"
              :clickable="false"
              :show-bubble="false"
              :loop="true"
              :autoplay="true"
            />

            <div class="companion-ripples"><i /><i /><i /></div>
            <p><span /> 家庭照护空间已被温柔唤醒</p>
          </aside>
        </main>

        <p class="warm-boot-trust"><span aria-hidden="true">⌂</span> 本地优先 · 家庭健康数据留在可信空间</p>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.warm-boot {
  --boot-pine: #3f695c;
  --boot-pine-deep: #2d5146;
  --boot-sage: #9caf91;
  --boot-paper: #f8f3e8;
  --boot-cream: #fffaf0;
  --boot-terracotta: #d77a55;
  --boot-gold: #d9ad63;
  --boot-ink: #423d34;
  --boot-muted: #756d61;
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  overflow: hidden;
  color: var(--boot-ink);
  background:
    radial-gradient(circle at 48% 42%, rgba(255, 253, 247, .96) 0 22%, rgba(255, 252, 244, .68) 54%, transparent 76%),
    linear-gradient(118deg, #f6f0e3 0%, #fcf8ef 48%, #f8efe2 100%);
}

.warm-boot-paper {
  position: absolute;
  inset: 0;
  opacity: .42;
  pointer-events: none;
  background-image:
    radial-gradient(circle at 20% 30%, rgba(83, 103, 79, .1) 0 .7px, transparent .9px),
    radial-gradient(circle at 70% 64%, rgba(160, 113, 72, .1) 0 .65px, transparent .85px),
    repeating-linear-gradient(7deg, rgba(82, 73, 57, .025) 0 1px, transparent 1px 5px);
  background-size: 9px 11px, 13px 15px, 100% 7px;
  mix-blend-mode: multiply;
}

.warm-boot-wash {
  position: absolute;
  border-radius: 42% 58% 54% 46%;
  filter: blur(18px);
  opacity: .52;
  animation: watercolor-breathe 7s ease-in-out infinite alternate;
}

.warm-boot-wash-left {
  width: 38vw;
  height: 44vw;
  left: -20vw;
  bottom: -23vw;
  background: radial-gradient(circle, rgba(174, 193, 167, .45), rgba(212, 220, 195, .16) 54%, transparent 72%);
}

.warm-boot-wash-right {
  width: 46vw;
  height: 54vw;
  right: -18vw;
  bottom: -26vw;
  background: radial-gradient(circle, rgba(235, 177, 119, .52), rgba(242, 204, 161, .22) 52%, transparent 73%);
  animation-delay: -2.6s;
}

.warm-boot-plant {
  position: absolute;
  width: clamp(190px, 18vw, 330px);
  overflow: visible;
  fill: rgba(118, 146, 106, .12);
  stroke: rgba(78, 111, 83, .22);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: blur(.15px);
  pointer-events: none;
}

.warm-boot-plant-left { left: -3.5vw; top: -4vh; transform: rotate(-7deg); }
.warm-boot-plant-right { right: -3vw; bottom: -11vh; transform: rotate(4deg); }

.warm-boot-leaf {
  position: absolute;
  width: 15px;
  height: 8px;
  border-radius: 100% 0 100% 0;
  background: rgba(104, 139, 96, .5);
  box-shadow: 0 4px 10px rgba(64, 96, 71, .12);
  animation: leaf-drift 6s ease-in-out infinite;
}

.leaf-one { left: 14%; top: 25%; transform: rotate(28deg); }
.leaf-two { right: 18%; top: 30%; animation-delay: -2s; transform: rotate(-32deg) scale(.78); }
.leaf-three { right: 11%; bottom: 23%; animation-delay: -4s; transform: rotate(51deg) scale(.65); }

.warm-boot-spark,
.companion-glint {
  position: absolute;
  width: 8px;
  height: 8px;
  background: rgba(255, 252, 235, .94);
  clip-path: polygon(50% 0, 61% 38%, 100% 50%, 61% 62%, 50% 100%, 39% 62%, 0 50%, 39% 38%);
  filter: drop-shadow(0 0 7px rgba(222, 175, 99, .55));
  animation: glint 2.8s ease-in-out infinite;
}

.spark-one { left: 22%; bottom: 25%; }
.spark-two { right: 9%; top: 18%; animation-delay: -1.2s; transform: scale(1.4); }

.warm-boot-stage {
  position: relative;
  z-index: 2;
  width: 100%;
  min-height: min(790px, calc(100vh - 70px));
  display: grid;
  place-items: center;
}

.warm-boot-core {
  width: min(600px, calc(100vw - 48px));
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.warm-boot-heading { display: flex; flex-direction: column; align-items: center; }
.warm-boot-emblem { width: 56px; height: 56px; color: var(--boot-pine); animation: emblem-appear .75s cubic-bezier(.22, 1.3, .36, 1) both; }
.warm-boot-emblem svg { width: 100%; height: 100%; }
.warm-boot-emblem path { stroke: currentColor; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.warm-boot-emblem .emblem-heart { fill: rgba(214, 166, 91, .76); stroke: none; }

.warm-boot-kicker {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 8px 0 0;
  color: #8a7059;
  font-size: .78rem;
  font-weight: 700;
  letter-spacing: .17em;
  opacity: 0;
  animation: text-fade-up .55s ease .14s both;
}

.warm-boot-kicker i { width: 4px; height: 4px; border-radius: 50%; background: var(--boot-terracotta); }
.warm-boot h2 {
  margin: 9px 0 0;
  color: var(--boot-pine-deep);
  font-family: Georgia, 'Noto Serif SC', STSong, SimSun, 'Microsoft YaHei', serif;
  font-size: clamp(2.35rem, 3.1vw, 3.25rem);
  font-weight: 600;
  letter-spacing: .09em;
  line-height: 1.12;
  text-shadow: 0 2px 18px rgba(66, 87, 66, .08);
  opacity: 0;
  animation: text-fade-up .55s ease .22s both;
}

.warm-boot-subtitle {
  margin: 13px 0 0;
  color: #846d58;
  font-family: Georgia, 'Noto Serif SC', STSong, SimSun, 'Microsoft YaHei', serif;
  font-size: 1rem;
  letter-spacing: .08em;
  opacity: 0;
  animation: text-fade-up .55s ease .3s both;
}

.warm-boot-heading-sprout { display: block; margin-top: 8px; color: rgba(116, 139, 98, .56); font-size: 1.35rem; line-height: .7; transform: rotate(-18deg); }

.warm-boot-phases {
  width: 100%;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 9px;
  opacity: 0;
  animation: text-fade-up .58s ease .38s both;
}

.warm-boot-phase {
  position: relative;
  min-height: 64px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 9px 18px 9px 14px;
  border: 1px solid rgba(151, 126, 91, .2);
  border-radius: 14px;
  background: linear-gradient(110deg, rgba(255, 255, 252, .84), rgba(252, 248, 238, .72));
  box-shadow: 0 8px 20px rgba(92, 73, 50, .055), inset 0 1px rgba(255, 255, 255, .72);
  text-align: left;
  transition: transform .34s ease, border-color .34s ease, background .34s ease, opacity .34s ease;
}

.warm-boot-phase:not(:last-child)::after {
  content: '';
  position: absolute;
  z-index: -1;
  left: 33px;
  top: calc(100% + 1px);
  width: 1px;
  height: 11px;
  background: repeating-linear-gradient(to bottom, rgba(63, 105, 92, .55) 0 3px, transparent 3px 6px);
}

.warm-boot-phase.complete { opacity: .83; }
.warm-boot-phase.active {
  border-color: rgba(63, 105, 92, .42);
  background: linear-gradient(108deg, rgba(238, 246, 237, .94), rgba(251, 247, 231, .88));
  box-shadow: 0 10px 26px rgba(63, 90, 71, .1), inset 3px 0 rgba(82, 126, 104, .42);
  transform: translateX(4px) scale(1.012);
}

.warm-boot-phase.phase-ready.active { border-color: rgba(63, 105, 92, .56); background: linear-gradient(108deg, rgba(228, 241, 227, .98), rgba(249, 244, 221, .94)); }
.warm-boot-phase.pending { opacity: .58; }

.warm-boot-marker {
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(157, 132, 94, .25);
  border-radius: 50%;
  color: var(--boot-pine);
  background: rgba(255, 253, 246, .9);
  box-shadow: 0 3px 10px rgba(72, 65, 48, .06);
}

.warm-boot-marker svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.warm-boot-phase.complete .warm-boot-marker { border-color: rgba(63, 105, 92, .26); background: rgba(239, 246, 237, .94); }
.warm-boot-phase.active .warm-boot-marker { border-color: rgba(63, 105, 92, .45); box-shadow: 0 0 0 5px rgba(100, 143, 118, .08); }

.marker-pulse {
  width: 15px;
  height: 15px;
  border: 4px solid rgba(255, 255, 255, .8);
  border-radius: 50%;
  background: var(--boot-pine);
  box-shadow: 0 0 0 3px rgba(63, 105, 92, .18), 0 0 15px rgba(63, 105, 92, .28);
  animation: marker-pulse-anim 1.35s ease-in-out infinite;
}

.marker-wait { width: 7px; height: 7px; border-radius: 50%; background: rgba(151, 132, 101, .35); }
.warm-boot-phase-copy { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.warm-boot-phase-copy strong { overflow: hidden; color: #3f3a32; font-size: .88rem; font-weight: 760; letter-spacing: .015em; text-overflow: ellipsis; white-space: nowrap; }
.warm-boot-phase-copy small { color: var(--boot-muted); font-size: .76rem; letter-spacing: .03em; }
.warm-boot-phase.active .warm-boot-phase-copy strong { color: var(--boot-pine-deep); }

.warm-boot-phase-status {
  flex: 0 0 auto;
  min-width: 54px;
  padding: 5px 10px;
  border-radius: 999px;
  color: var(--boot-pine-deep);
  background: rgba(223, 233, 218, .68);
  font-size: .75rem;
  font-weight: 650;
  text-align: center;
}

.warm-boot-phase.pending .warm-boot-phase-status { color: #897d6d; background: rgba(232, 224, 207, .58); }

.warm-boot-progress {
  width: 100%;
  height: 5px;
  margin-top: 22px;
  border-radius: 999px;
  background: rgba(159, 138, 103, .14);
  box-shadow: inset 0 1px 2px rgba(111, 85, 53, .08);
}

.warm-boot-progress > span {
  position: relative;
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #8fb49f 0%, var(--boot-pine) 54%, #d9b26b 87%, #e4bd73 100%);
  box-shadow: 0 0 10px rgba(71, 110, 91, .16);
  transition: width .48s cubic-bezier(.22, .9, .33, 1);
}

.warm-boot-progress > span i {
  position: absolute;
  top: 50%;
  right: -5px;
  width: 10px;
  height: 10px;
  border: 2px solid rgba(255, 255, 255, .9);
  border-radius: 50%;
  background: #e6bd72;
  box-shadow: 0 0 0 4px rgba(230, 189, 114, .13), 0 0 14px rgba(218, 157, 66, .5);
  transform: translateY(-50%);
  animation: progress-glow 1.4s ease-in-out infinite;
}

.warm-boot-skip {
  margin-top: 22px;
  padding: 9px 19px;
  border: 1px solid rgba(157, 132, 94, .22);
  border-radius: 999px;
  color: #827568;
  background: rgba(255, 251, 242, .56);
  box-shadow: 0 4px 14px rgba(104, 80, 48, .04);
  font-size: .8rem;
  cursor: pointer;
  backdrop-filter: blur(8px);
  transition: transform .2s ease, background .2s ease, border-color .2s ease;
}

.warm-boot-skip:hover { transform: translateY(-1px); border-color: rgba(63, 105, 92, .3); background: rgba(255, 253, 247, .9); }
.warm-boot-skip:focus-visible { outline: 2px solid rgba(63, 105, 92, .46); outline-offset: 3px; }
.warm-boot-skip kbd { margin-left: 6px; padding: 2px 7px; border: 0; border-radius: 7px; color: #876d57; background: rgba(151, 126, 91, .11); font: inherit; }

.warm-boot-companion {
  position: absolute;
  top: 50%;
  right: clamp(32px, 6vw, 120px);
  width: min(20vw, 340px);
  aspect-ratio: 1 / 1.08;
  display: grid;
  place-items: center;
  opacity: 0;
  translate: 0 -50%;
  animation: companion-arrive .9s cubic-bezier(.22, 1.1, .36, 1) .52s both;
}

.companion-aura { position: absolute; border-radius: 50%; filter: blur(3px); animation: aura-breathe 4.5s ease-in-out infinite; }
.aura-one { width: 84%; height: 84%; background: radial-gradient(circle, rgba(255, 249, 223, .82), rgba(235, 190, 126, .15) 48%, transparent 72%); }
.aura-two { width: 62%; height: 62%; background: radial-gradient(circle, rgba(255, 255, 250, .92), rgba(166, 192, 161, .2) 50%, transparent 72%); animation-delay: -2s; }

.companion-orbit {
  position: absolute;
  left: 50%;
  top: 64%;
  border: 1px solid rgba(255, 255, 255, .76);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 0 22px rgba(224, 174, 101, .12);
  animation: orbit-breathe 3.2s ease-in-out infinite;
}

.orbit-one { width: 90%; height: 24%; }
.orbit-two { width: 70%; height: 17%; animation-delay: -.9s; }
.sprout-friend { position: relative; z-index: 2; width: 61%; overflow: visible; animation: friend-float 3.8s ease-in-out infinite; }
.companion-ripples { position: absolute; z-index: 1; left: 50%; top: 75%; width: 85%; height: 19%; transform: translate(-50%, -50%); }
.companion-ripples i { position: absolute; inset: 0; border: 1px solid rgba(255, 255, 255, .78); border-radius: 50%; animation: ripple 3s ease-out infinite; }
.companion-ripples i:nth-child(2) { animation-delay: -1s; }
.companion-ripples i:nth-child(3) { animation-delay: -2s; }
.companion-glint { z-index: 3; }
.glint-one { left: 17%; top: 35%; }
.glint-two { right: 12%; top: 24%; width: 13px; height: 13px; animation-delay: -.9s; }
.glint-three { right: 20%; bottom: 28%; width: 6px; height: 6px; animation-delay: -1.7s; }

.warm-boot-companion p {
  position: absolute;
  z-index: 4;
  left: 50%;
  bottom: 5%;
  margin: 0;
  padding: 8px 14px;
  border: 1px solid rgba(128, 145, 112, .16);
  border-radius: 999px;
  color: rgba(69, 91, 73, .76);
  background: rgba(255, 252, 242, .5);
  font-family: Georgia, 'Noto Serif SC', STSong, SimSun, 'Microsoft YaHei', serif;
  font-size: .72rem;
  letter-spacing: .05em;
  white-space: nowrap;
  backdrop-filter: blur(5px);
  transform: translateX(-50%);
}

.warm-boot-companion p span { display: inline-block; width: 5px; height: 5px; margin-right: 6px; border-radius: 50%; background: #79a083; box-shadow: 0 0 0 3px rgba(121, 160, 131, .13); vertical-align: 1px; }
.warm-boot-trust { position: absolute; z-index: 3; left: 50%; bottom: 22px; margin: 0; color: rgba(97, 87, 72, .58); font-size: .7rem; letter-spacing: .08em; transform: translateX(-50%); white-space: nowrap; }
.warm-boot-trust span { margin-right: 5px; color: rgba(63, 105, 92, .62); }

@keyframes emblem-appear { from { opacity: 0; transform: scale(.72) translateY(14px); } to { opacity: 1; transform: scale(1) translateY(0); } }
@keyframes text-fade-up { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes marker-pulse-anim { 0%, 100% { transform: scale(.9); opacity: .84; } 50% { transform: scale(1.13); opacity: 1; } }
@keyframes progress-glow { 0%, 100% { transform: translateY(-50%) scale(.86); } 50% { transform: translateY(-50%) scale(1.13); } }
@keyframes watercolor-breathe { from { transform: scale(.95) rotate(-2deg); opacity: .42; } to { transform: scale(1.07) rotate(2deg); opacity: .58; } }
@keyframes leaf-drift { 0%, 100% { translate: 0 0; rotate: -8deg; } 50% { translate: 12px 14px; rotate: 19deg; } }
@keyframes glint { 0%, 100% { opacity: .25; transform: scale(.65) rotate(0deg); } 50% { opacity: 1; transform: scale(1.15) rotate(45deg); } }
@keyframes companion-arrive { from { opacity: 0; transform: translateY(20px) scale(.9); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes aura-breathe { 0%, 100% { transform: scale(.94); opacity: .64; } 50% { transform: scale(1.06); opacity: .95; } }
@keyframes orbit-breathe { 0%, 100% { opacity: .45; transform: translate(-50%, -50%) scale(.93); } 50% { opacity: .9; transform: translate(-50%, -50%) scale(1.05); } }
@keyframes friend-float { 0%, 100% { transform: translateY(4px) rotate(-.5deg); } 50% { transform: translateY(-8px) rotate(.5deg); } }
@keyframes ripple { 0% { opacity: .8; transform: scale(.55); } 85%, 100% { opacity: 0; transform: scale(1.18); } }

.boot-fade-enter-active,
.boot-fade-leave-active { transition: opacity .46s ease; }
.boot-fade-enter-from,
.boot-fade-leave-to { opacity: 0; }

@media (max-width: 1260px) {
  .warm-boot-companion { display: none; }
}

@media (max-width: 640px) {
  .warm-boot-stage { min-height: calc(100vh - 38px); }
  .warm-boot-core { width: calc(100vw - 32px); }
  .warm-boot h2 { font-size: 2rem; }
  .warm-boot-phase { min-height: 59px; padding: 8px 12px; gap: 10px; }
  .warm-boot-marker { flex-basis: 32px; width: 32px; height: 32px; }
  .warm-boot-phase:not(:last-child)::after { left: 28px; }
  .warm-boot-phase-copy strong { font-size: .78rem; }
  .warm-boot-phase-status { min-width: 48px; padding-inline: 8px; }
  .warm-boot-trust { bottom: 10px; font-size: .62rem; }
}

@media (max-height: 790px) and (min-width: 981px) {
  .warm-boot-stage { min-height: calc(100vh - 28px); transform: scale(.9); }
  .warm-boot-trust { bottom: 8px; }
}

@media (prefers-reduced-motion: reduce) {
  .warm-boot *,
  .warm-boot *::before,
  .warm-boot *::after { animation-duration: .001ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; }
}
</style>
