<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  COMPANION_PET_ANIMATIONS,
  COMPANION_PET_FRAME_SOURCES,
  companionPetDuration,
  companionPetFrameCount,
  normalizeCompanionPetFrame,
  type CompanionPetPlacement,
  type CompanionPetSize,
  type CompanionPetState,
} from '../assets/pet/manifest'

const props = withDefaults(defineProps<{
  state?: CompanionPetState
  size?: CompanionPetSize
  clickable?: boolean
  showBubble?: boolean
  bubbleText?: string
  loop?: boolean
  autoplay?: boolean
  placement?: CompanionPetPlacement
  frameSources?: readonly string[]
}>(), {
  state: 'idle',
  size: 'medium',
  clickable: false,
  showBubble: false,
  bubbleText: '',
  loop: true,
  autoplay: true,
  placement: 'inline',
  frameSources: undefined,
})

const emit = defineEmits<{
  click: [state: CompanionPetState]
  complete: [state: CompanionPetState]
}>()

const frame = ref(0)
const hovered = ref(false)
const reactionState = ref<CompanionPetState | null>(null)
let frameTimer: ReturnType<typeof setTimeout> | null = null
let reactionTimer: ReturnType<typeof setTimeout> | null = null

const activeState = computed<CompanionPetState>(() => {
  if (reactionState.value) return reactionState.value
  if (hovered.value && props.clickable && props.state === 'idle') return 'happy'
  return props.state
})

const animation = computed(() => COMPANION_PET_ANIMATIONS[activeState.value])
const sources = computed<readonly string[]>(() => (
  props.frameSources ?? COMPANION_PET_FRAME_SOURCES[activeState.value] ?? []
))
const frameCount = computed(() => sources.value.length || companionPetFrameCount(activeState.value))
const currentFrame = computed(() => normalizeCompanionPetFrame(frame.value, frameCount.value))
const currentFrameSource = computed(() => sources.value[currentFrame.value] ?? '')
const accessibleLabel = computed(() => `小芽精灵，${animation.value.label}`)

const phase = computed(() => {
  if (frameCount.value <= 1) return 0
  return currentFrame.value / (frameCount.value - 1)
})

const frameStyle = computed(() => {
  const wave = [0, -18, -38, -54, -34, -8][currentFrame.value % 6] ?? 0
  const bob = [0, -1, -3, -2, 0, 1][currentFrame.value % 6] ?? 0
  const sway = [-2, 0, 2, 3, 1, -1][currentFrame.value % 6] ?? 0
  const breathe = [1, 1.01, 1.018, 1.012, 1.004, .996][currentFrame.value % 6] ?? 1
  return {
    '--pet-frame': String(currentFrame.value),
    '--pet-phase': String(phase.value),
    '--pet-wave': `${wave}deg`,
    '--pet-bob': `${bob}px`,
    '--pet-sway': `${sway}deg`,
    '--pet-breathe': String(breathe),
  }
})

function stopFrameTimer(): void {
  if (frameTimer) clearTimeout(frameTimer)
  frameTimer = null
}

function scheduleNextFrame(): void {
  stopFrameTimer()
  if (!props.autoplay || frameCount.value <= 1) return
  frameTimer = setTimeout(() => {
    const next = frame.value + 1
    if (next >= frameCount.value) {
      const shouldLoop = reactionState.value ? false : (props.loop && animation.value.loop)
      if (!shouldLoop) {
        frame.value = frameCount.value - 1
        emit('complete', activeState.value)
        return
      }
      frame.value = 0
    } else {
      frame.value = next
    }
    scheduleNextFrame()
  }, animation.value.frameMs)
}

function restartAnimation(): void {
  frame.value = 0
  scheduleNextFrame()
}

function clearReaction(): void {
  if (reactionTimer) clearTimeout(reactionTimer)
  reactionTimer = null
  reactionState.value = null
}

function playReaction(state: CompanionPetState, thenState?: CompanionPetState): void {
  clearReaction()
  reactionState.value = state
  restartAnimation()
  reactionTimer = setTimeout(() => {
    if (thenState) {
      reactionState.value = thenState
      restartAnimation()
      reactionTimer = setTimeout(() => {
        reactionState.value = null
        restartAnimation()
      }, companionPetDuration(thenState))
      return
    }
    reactionState.value = null
    restartAnimation()
  }, companionPetDuration(state))
}

function handleClick(): void {
  if (!props.clickable) return
  playReaction('wave', 'happy')
  emit('click', props.state)
}

watch([activeState, () => props.autoplay, () => props.loop, frameCount], restartAnimation)
onMounted(restartAnimation)
onBeforeUnmount(() => {
  stopFrameTimer()
  clearReaction()
})
</script>

<template>
  <component
    :is="clickable ? 'button' : 'div'"
    class="companion-pet"
    :class="[
      `companion-pet--${size}`,
      `companion-pet--${placement}`,
      `companion-pet--${activeState}`,
      `companion-pet--frame-${currentFrame}`,
    ]"
    :style="frameStyle"
    :type="clickable ? 'button' : undefined"
    :aria-label="clickable ? `${accessibleLabel}，点击和它打招呼` : accessibleLabel"
    :role="clickable ? undefined : 'img'"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
    @click="handleClick"
  >
    <Transition name="companion-bubble">
      <span v-if="showBubble && bubbleText" class="companion-pet__bubble" role="status">
        {{ bubbleText }}
      </span>
    </Transition>

    <span class="companion-pet__stage" aria-hidden="true">
      <img
        v-if="currentFrameSource"
        class="companion-pet__frame"
        :src="currentFrameSource"
        alt=""
        draggable="false"
      />
      <svg v-else class="companion-pet__vector" viewBox="0 0 120 132" fill="none">
        <ellipse class="pet-ground" cx="60" cy="120" rx="31" ry="4.5" />
        <g class="pet-character">
          <g class="pet-sprout">
            <path class="pet-leaf pet-leaf--left" d="M60 27C48 25 42 17 43 7c10 1 17 7 18 19Z" />
            <path class="pet-leaf pet-leaf--right" d="M60 27c2-12 10-19 21-19 0 10-7 17-21 19Z" />
            <path d="M60 27v8" class="pet-line" />
          </g>

          <path class="pet-body" d="M23 68c0-25 15-41 37-41s37 16 37 41v17c0 22-15 35-37 35S23 107 23 85V68Z" />
          <g class="pet-arm pet-arm--left">
            <path d="M27 76c-10 4-13 13-7 20 7 1 13-4 16-12" />
          </g>
          <g class="pet-arm pet-arm--right">
            <path d="M93 76c10 4 13 13 7 20-7 1-13-4-16-12" />
          </g>
          <path class="pet-foot pet-foot--left" d="M43 113c-1 9-5 12-12 12 1-7 4-12 9-15" />
          <path class="pet-foot pet-foot--right" d="M77 113c1 9 5 12 12 12-1-7-4-12-9-15" />

          <ellipse class="pet-cheek pet-cheek--left" cx="40" cy="78" rx="8" ry="5" />
          <ellipse class="pet-cheek pet-cheek--right" cx="80" cy="78" rx="8" ry="5" />

          <g class="pet-face pet-face--open">
            <ellipse cx="46" cy="66" rx="4" ry="5.5" />
            <ellipse cx="74" cy="66" rx="4" ry="5.5" />
            <circle cx="47" cy="64" r="1.1" />
            <circle cx="75" cy="64" r="1.1" />
          </g>
          <g class="pet-face pet-face--happy">
            <path d="M41 68c3-5 7-5 10 0M69 68c3-5 7-5 10 0" />
          </g>
          <g class="pet-face pet-face--sleep">
            <path d="M41 67c3 3 7 3 10 0M69 67c3 3 7 3 10 0" />
          </g>
          <g class="pet-brow">
            <path d="M41 58c3-2 6-2 9 0M70 58c3-2 6-2 9 0" />
          </g>
          <path class="pet-mouth pet-mouth--smile" d="M54 78c4 5 8 5 12 0" />
          <path class="pet-mouth pet-mouth--open" d="M53 77c4 8 10 8 14 0-5 2-9 2-14 0Z" />
          <path class="pet-mouth pet-mouth--tiny" d="M57 78c2 2 4 2 6 0" />

          <g class="pet-listen-mark">
            <path d="M92 55c5 4 5 10 0 14M98 51c8 7 8 16 0 23" />
          </g>
          <g class="pet-reminder-badge">
            <circle cx="93" cy="42" r="8" />
            <path d="M93 38v5M93 46h.1" />
          </g>
          <g class="pet-success-mark">
            <path d="m87 43 4 4 8-10" />
          </g>
        </g>
      </svg>
    </span>
  </component>
</template>

<style scoped>
.companion-pet {
  --pet-size: 112px;
  --pet-outline: #496c5b;
  --pet-outline-soft: #75917d;
  --pet-body: #fff8e8;
  --pet-leaf: #789b76;
  --pet-leaf-light: #9fb494;
  --pet-blush: #f2b39b;
  --pet-shadow: rgba(89, 104, 79, .15);
  appearance: none;
  position: relative;
  display: inline-grid;
  width: var(--pet-size);
  padding: 0;
  border: 0;
  color: var(--pet-outline);
  background: transparent;
  font: inherit;
  vertical-align: middle;
}

button.companion-pet { cursor: pointer; }
button.companion-pet:focus-visible { outline: 2px solid color-mix(in srgb, var(--pet-outline) 62%, white); outline-offset: 5px; border-radius: 34%; }
.companion-pet--small { --pet-size: 72px; }
.companion-pet--medium { --pet-size: 112px; }
.companion-pet--large { --pet-size: 230px; }
.companion-pet--floating { position: fixed; right: 24px; bottom: 20px; z-index: 1200; filter: drop-shadow(0 12px 18px var(--pet-shadow)); }
.companion-pet--card { align-self: end; margin-inline: auto 0; }
.companion-pet--empty { margin: 4px auto 10px; }

.companion-pet__stage { position: relative; display: block; width: 100%; aspect-ratio: 120 / 132; }
.companion-pet__frame,
.companion-pet__vector { display: block; width: 100%; height: 100%; object-fit: contain; overflow: visible; }
.companion-pet__frame { user-select: none; }
.companion-pet__vector { filter: drop-shadow(0 8px 10px var(--pet-shadow)); }

.companion-pet__bubble {
  position: absolute;
  z-index: 2;
  right: 72%;
  bottom: 78%;
  width: max-content;
  max-width: 240px;
  padding: 9px 12px;
  border: 1px solid rgba(73, 108, 91, .2);
  border-radius: 14px 14px 4px;
  color: #4a493f;
  background: rgba(255, 252, 243, .96);
  box-shadow: 0 10px 25px rgba(70, 82, 64, .13);
  font-size: 12px;
  line-height: 1.55;
  text-align: left;
}

.pet-ground { fill: rgba(211, 190, 142, .15); transform-origin: center; opacity: .58; }
.pet-character { transform-box: fill-box; transform-origin: 50% 92%; transform: translateY(var(--pet-bob)) rotate(var(--pet-sway)) scale(var(--pet-breathe)); transition: transform 85ms linear; }
.pet-body { fill: var(--pet-body); stroke: var(--pet-outline); stroke-width: 3; stroke-linejoin: round; }
.pet-line,
.pet-arm path,
.pet-foot,
.pet-face--happy path,
.pet-face--sleep path,
.pet-brow path,
.pet-mouth,
.pet-listen-mark path,
.pet-reminder-badge path,
.pet-success-mark path { fill: none; stroke: var(--pet-outline); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.pet-leaf { stroke: var(--pet-outline); stroke-width: 2.7; stroke-linejoin: round; }
.pet-leaf--left { fill: var(--pet-leaf-light); }
.pet-leaf--right { fill: var(--pet-leaf); }
.pet-sprout { transform-box: fill-box; transform-origin: 50% 100%; }
.pet-arm { transform-box: fill-box; transform-origin: 50% 75%; transition: transform 85ms linear; }
.pet-arm path { fill: var(--pet-body); }
.pet-foot { fill: var(--pet-body); }
.pet-cheek { fill: var(--pet-blush); opacity: .66; }
.pet-face--open ellipse { fill: var(--pet-outline); }
.pet-face--open circle { fill: #fffdf6; }
.pet-face--happy,
.pet-face--sleep,
.pet-brow,
.pet-mouth--open,
.pet-mouth--tiny,
.pet-listen-mark,
.pet-reminder-badge,
.pet-success-mark { display: none; }
.pet-mouth--open { fill: #d98c72; stroke-width: 2.5; }

.companion-pet--blink .pet-face--open { display: none; }
.companion-pet--blink.companion-pet--frame-1 .pet-face--sleep,
.companion-pet--blink.companion-pet--frame-2 .pet-face--sleep { display: block; }
.companion-pet--happy .pet-face--open,
.companion-pet--cheer .pet-face--open,
.companion-pet--shy .pet-face--open,
.companion-pet--success .pet-face--open { display: none; }
.companion-pet--happy .pet-face--happy,
.companion-pet--cheer .pet-face--happy,
.companion-pet--shy .pet-face--happy,
.companion-pet--success .pet-face--happy { display: block; }
.companion-pet--sleep .pet-face--open { display: none; }
.companion-pet--sleep .pet-face--sleep { display: block; }
.companion-pet--sleep .pet-mouth--smile { opacity: .48; }
.companion-pet--sleep .pet-character { transform: translateY(calc(var(--pet-bob) + 5px)) rotate(-2deg) scale(1.03, .96); }
.companion-pet--sleep .pet-sprout { transform: rotate(-8deg); }

.companion-pet--wave .pet-arm--left { transform: translate(-4px, -16px) rotate(var(--pet-wave)); }
.companion-pet--wave .pet-mouth--smile,
.companion-pet--cheer .pet-mouth--smile,
.companion-pet--success .pet-mouth--smile { display: none; }
.companion-pet--wave .pet-mouth--open,
.companion-pet--cheer .pet-mouth--open,
.companion-pet--success .pet-mouth--open { display: block; }
.companion-pet--cheer .pet-arm--left { transform: translate(-5px, -18px) rotate(-55deg); }
.companion-pet--cheer .pet-arm--right { transform: translate(5px, -18px) rotate(55deg); }
.companion-pet--cheer .pet-character,
.companion-pet--success .pet-character { transform: translateY(calc(var(--pet-bob) - 3px)) scale(var(--pet-breathe)); }
.companion-pet--success .pet-success-mark { display: block; }

.companion-pet--think .pet-brow { display: block; }
.companion-pet--think .pet-arm--left { transform: translate(7px, -7px) rotate(-17deg); }
.companion-pet--think .pet-mouth--smile { display: none; }
.companion-pet--think .pet-mouth--tiny { display: block; }
.companion-pet--think .pet-character { transform: translateY(var(--pet-bob)) rotate(-2deg) scale(var(--pet-breathe)); }
.companion-pet--shy .pet-cheek { opacity: .9; }
.companion-pet--shy .pet-arm--left { transform: translate(7px, -1px) rotate(-8deg); }
.companion-pet--shy .pet-arm--right { transform: translate(-7px, -1px) rotate(8deg); }
.companion-pet--shy .pet-character { transform: translateY(var(--pet-bob)) rotate(2deg) scale(.98); }

.companion-pet--loading .pet-sprout { transform: rotate(var(--pet-sway)); }
.companion-pet--loading .pet-ground { opacity: calc(.28 + var(--pet-phase) * .35); }
.companion-pet--point .pet-arm--right { transform: translate(8px, -9px) rotate(48deg); }
.companion-pet--point .pet-character { transform: translateY(var(--pet-bob)) rotate(-1deg) scale(var(--pet-breathe)); }
.companion-pet--listening .pet-listen-mark { display: block; opacity: calc(.38 + var(--pet-phase) * .6); }
.companion-pet--listening .pet-character { transform: translateY(var(--pet-bob)) rotate(1deg) scale(var(--pet-breathe)); }
.companion-pet--reminder .pet-reminder-badge { display: block; }
.companion-pet--reminder .pet-reminder-badge circle { fill: #f1d8ad; stroke: var(--pet-outline); stroke-width: 2; }
.companion-pet--reminder .pet-cheek { opacity: .82; }

.companion-bubble-enter-active,
.companion-bubble-leave-active { transition: opacity .2s ease, transform .2s ease; }
.companion-bubble-enter-from,
.companion-bubble-leave-to { opacity: 0; transform: translateY(5px) scale(.96); }

@media (prefers-reduced-motion: reduce) {
  .pet-character,
  .pet-arm,
  .pet-sprout { transition: none; }
}
</style>
