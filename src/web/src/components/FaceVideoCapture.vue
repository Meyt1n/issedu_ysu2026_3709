<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { isSpeechOutputSupported, speakText, stopSpeaking } from '../assistant/voice'
import {
  faceCaptureDoneSpeech,
  faceCaptureIntro,
  faceCaptureStartLabel,
  faceCaptureSteps,
  faceStepLabel,
  type FaceCaptureMode,
} from '../ui/faceCaptureGuidance'

const props = withDefaults(defineProps<{
  disabled?: boolean
  mode?: FaceCaptureMode
  showFallback?: boolean
  /** Shorter layout for welcome/login card — hide long bullet lists. */
  compact?: boolean
  /** Default on for elder-friendly coaching; user can mute. */
  voiceEnabled?: boolean
  /** Bound welcome page: open the camera once without a second click. */
  autoStart?: boolean
}>(), {
  mode: 'login',
  showFallback: true,
  compact: false,
  voiceEnabled: true,
  autoStart: false,
})

const emit = defineEmits<{
  captured: [frames: File[]]
  fallback: []
}>()

// Server-side face frame gate floor (ensure_face_frame_quality): short side
// >= 360 and long side >= 480. Frames below that are rejected as
// FACE_FRAME_LOW_QUALITY, so fail fast with a friendly message instead.
const MIN_FRAME_SHORT_SIDE = 360
const MIN_FRAME_LONG_SIDE = 480
const MAX_FRAME_WIDTH = 960

const video = ref<HTMLVideoElement | null>(null)
const capturing = ref(false)
const error = ref('')
const progress = ref('')
const stepIndex = ref(-1)
const countdown = ref(0)
const voiceOn = ref(props.voiceEnabled && isSpeechOutputSupported())
const voiceSupported = isSpeechOutputSupported()
let stream: MediaStream | null = null
let autoStartAttempted = false

const steps = computed(() => faceCaptureSteps(props.mode))
const intro = computed(() => faceCaptureIntro(props.mode))
const activeStep = computed(() => (stepIndex.value >= 0 ? steps.value[stepIndex.value] : null))
const overlayLabel = computed(() => {
  if (countdown.value > 0) return String(countdown.value)
  if (activeStep.value) return activeStep.value.title
  if (capturing.value) return '正在打开摄像头…'
  return '把脸放进圆圈'
})
const modeLabel = computed(() => (props.mode === 'registration' ? '录入人脸' : '刷脸登录'))
const startLabel = computed(() => faceCaptureStartLabel(props.mode))
const idleHint = computed(() => (
  props.mode === 'login' && props.compact
    ? '点「刷脸进入」，或稍等自动开摄'
    : '坐稳后点下面的大按钮开始'
))

function stopCamera(): void {
  for (const track of stream?.getTracks() ?? []) track.stop()
  stream = null
  if (video.value) video.value.srcObject = null
}

function wait(milliseconds: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, milliseconds))
}

function speak(text: string): void {
  if (!voiceOn.value || !text.trim()) return
  speakText(text)
}

async function speakAndPause(text: string, pauseMs: number): Promise<void> {
  speak(text)
  const estimated = Math.min(5200, Math.max(pauseMs, text.length * 95))
  await wait(estimated)
}

async function waitForVideoReady(element: HTMLVideoElement): Promise<void> {
  const deadline = Date.now() + 2500
  while (element.videoWidth <= 0 || element.videoHeight <= 0) {
    if (Date.now() >= deadline) throw new Error('CAMERA_NOT_READY')
    await wait(100)
  }
}

async function runCountdown(seconds: number): Promise<void> {
  for (let value = seconds; value >= 1; value -= 1) {
    countdown.value = value
    speak(String(value))
    await wait(900)
  }
  countdown.value = 0
}

async function capture(): Promise<void> {
  if (props.disabled || capturing.value) return
  error.value = ''
  progress.value = '正在打开摄像头，请稍等…'
  stepIndex.value = -1
  countdown.value = 0
  capturing.value = true
  const captureSteps = steps.value
  const stepTotal = captureSteps.length
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('CAMERA_UNAVAILABLE')
    // Login compact path: shorter intro so bound members get to the camera faster.
    if (props.mode === 'login' && props.compact) {
      speak(intro.value.speech)
      await wait(900)
    } else {
      await speakAndPause(intro.value.speech, 2200)
    }

    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: 'user',
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
      audio: false,
    })
    if (!video.value) throw new Error('CAMERA_UNAVAILABLE')
    video.value.srcObject = stream
    await video.value.play()
    await waitForVideoReady(video.value)
    await wait(400)

    const sourceWidth = video.value.videoWidth
    const sourceHeight = video.value.videoHeight
    if (
      Math.min(sourceWidth, sourceHeight) < MIN_FRAME_SHORT_SIDE
      || Math.max(sourceWidth, sourceHeight) < MIN_FRAME_LONG_SIDE
    ) {
      throw new Error('CAMERA_RESOLUTION_TOO_LOW')
    }

    const canvas = document.createElement('canvas')
    // Cap bandwidth at 960 wide, but never let the downscale push the short
    // side below the server-side face frame floor.
    let scale = Math.min(1, MAX_FRAME_WIDTH / sourceWidth)
    if (Math.min(sourceWidth, sourceHeight) * scale < MIN_FRAME_SHORT_SIDE) {
      scale = Math.min(1, MIN_FRAME_SHORT_SIDE / Math.min(sourceWidth, sourceHeight))
    }
    const width = Math.round(sourceWidth * scale)
    const height = Math.round(sourceHeight * scale)
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('CAMERA_UNAVAILABLE')

    const frames: File[] = []
    for (let index = 0; index < captureSteps.length; index += 1) {
      const step = captureSteps[index]
      stepIndex.value = index
      const label = faceStepLabel(index, stepTotal)
      progress.value = `${label}：${step.title}`
      const speakPause = props.mode === 'login' ? 1800 : 2600
      await speakAndPause(`${label}。${step.speech}`, speakPause)
      // Give elders time to actually turn before the shutter.
      if (index > 0) {
        progress.value = `${label}：请保持这个姿势…`
        speak('请保持这个姿势')
        await wait(props.mode === 'login' ? 900 : 1200)
      }
      await runCountdown(props.mode === 'login' ? 2 : 3)
      progress.value = `${label}：正在拍照…`
      context.drawImage(video.value, 0, 0, width, height)
      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9))
      if (!blob) throw new Error('CAMERA_UNAVAILABLE')
      frames.push(new File([blob], `face-${props.mode}-${index + 1}.jpg`, { type: 'image/jpeg' }))
      if (index < captureSteps.length - 1) await wait(500)
    }

    progress.value = props.mode === 'registration'
      ? '采集完成，正在本地安全校验…'
      : '采集完成，正在识别，请稍等…'
    await speakAndPause(faceCaptureDoneSpeech(props.mode), 1200)
    emit('captured', frames)
  } catch (cause) {
    stopSpeaking()
    error.value = cause instanceof DOMException && cause.name === 'NotAllowedError'
      ? '摄像头权限被拒绝。请家人在浏览器地址栏点一下允许摄像头，或改用数字密码登录。'
      : cause instanceof DOMException && cause.name === 'NotFoundError'
        ? '没有找到摄像头。请接好摄像头，或改用数字密码登录。'
        : cause instanceof Error && cause.message === 'CAMERA_RESOLUTION_TOO_LOW'
          ? '这个摄像头的画面太小，拍不清人脸。请换一个更清晰的摄像头，或改用数字密码登录。'
          : props.mode === 'registration'
            ? '摄像头打不开。请检查权限后重试，也可以让家人帮忙。'
            : '摄像头打不开或画面不好，请改用数字密码登录，也可以让家人帮忙。'
    speak(error.value)
    if (props.showFallback) emit('fallback')
  } finally {
    stopCamera()
    capturing.value = false
    stepIndex.value = -1
    countdown.value = 0
    progress.value = ''
  }
}

function toggleVoice(): void {
  voiceOn.value = !voiceOn.value
  if (!voiceOn.value) {
    stopSpeaking()
    return
  }
  speak('已打开语音提示')
}

function useFallback(): void {
  stopSpeaking()
  stopCamera()
  emit('fallback')
}

function maybeAutoStart(): void {
  if (!props.autoStart || props.disabled || autoStartAttempted || capturing.value) return
  autoStartAttempted = true
  void capture()
}

onMounted(() => {
  maybeAutoStart()
})

watch(
  () => [props.autoStart, props.disabled] as const,
  () => {
    maybeAutoStart()
  },
)

onBeforeUnmount(() => {
  stopSpeaking()
  stopCamera()
})
</script>

<template>
  <div
    class="face-capture face-capture--elder"
    :class="{ 'face-capture--compact': compact }"
    data-testid="face-video-capture"
  >
    <header class="face-capture-intro">
      <div class="face-capture-intro-top">
        <p class="face-capture-eyebrow">{{ modeLabel }} · 本地安全</p>
        <span class="face-capture-badge" :class="voiceOn ? 'is-on' : 'is-off'">
          {{ voiceSupported ? (voiceOn ? '语音已开' : '语音已关') : '无语音设备' }}
        </span>
      </div>
      <p class="face-capture-intro-title">{{ intro.title }}</p>
      <p v-if="compact" class="face-capture-compact-hint">
        把脸放进圆圈，听提示轻轻转一下头即可进入。
      </p>
      <ol v-else class="face-capture-bullets">
        <li v-for="item in intro.bullets" :key="item">
          <span class="face-capture-bullet-mark" aria-hidden="true" />
          <span>{{ item }}</span>
        </li>
      </ol>
    </header>

    <div
      class="face-stage"
      :class="{
        'is-live': capturing,
        'is-countdown': countdown > 0,
        'is-idle': !capturing,
      }"
    >
      <video
        ref="video"
        class="face-preview"
        muted
        playsinline
        aria-label="摄像头预览，请把脸放进中间圆圈"
      />
      <div class="face-stage-vignette" aria-hidden="true" />
      <div class="face-guide" aria-hidden="true">
        <div class="face-guide-ring">
          <div class="face-guide-oval" />
        </div>
        <div class="face-guide-markers">
          <i /><i /><i /><i />
        </div>
      </div>

      <div
        v-if="countdown > 0"
        class="face-countdown"
        role="status"
        aria-live="assertive"
      >
        {{ countdown }}
      </div>

      <div class="face-stage-banner" role="status" aria-live="polite">
        <p class="face-stage-kicker">
          {{ activeStep ? faceStepLabel(stepIndex, steps.length) : capturing ? '准备中' : '准备开始' }}
        </p>
        <strong :class="{ 'is-count': countdown > 0 }">{{ overlayLabel }}</strong>
        <span v-if="activeStep && countdown === 0">{{ activeStep.hint }}</span>
        <span v-else-if="!capturing">{{ idleHint }}</span>
      </div>
    </div>

    <p v-if="progress" class="notice face-progress" role="status" aria-live="polite">{{ progress }}</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>

    <div class="face-capture-actions">
      <button
        type="button"
        class="btn btn-primary face-capture-start"
        :disabled="disabled || capturing"
        @click="capture"
      >
        {{ capturing ? '请按提示做，不要走开' : startLabel }}
      </button>
      <button
        v-if="voiceSupported"
        type="button"
        class="btn btn-ghost btn-small face-voice-toggle"
        :aria-pressed="voiceOn"
        @click="toggleVoice"
      >
        {{ voiceOn ? '关闭语音' : '打开语音' }}
      </button>
      <button
        v-if="showFallback"
        type="button"
        class="btn btn-ghost btn-small"
        :disabled="capturing"
        @click="useFallback"
      >
        改用数字密码
      </button>
    </div>
    <p class="face-capture-footnote">
      <template v-if="compact">画面只在本机处理，不会上传照片。</template>
      <template v-else>
        画面只在本机内存里处理，不会上传人脸照片。听不清或不会操作时，请点“改用数字密码”，让家人帮忙也可以。
      </template>
    </p>
  </div>
</template>
