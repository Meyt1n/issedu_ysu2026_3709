<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

import { isSpeechOutputSupported, speakText, stopSpeaking } from '../assistant/voice'
import {
  FACE_CAPTURE_STEPS,
  faceCaptureDoneSpeech,
  faceCaptureIntro,
  faceStepLabel,
  type FaceCaptureMode,
} from '../ui/faceCaptureGuidance'

const props = withDefaults(defineProps<{
  disabled?: boolean
  mode?: FaceCaptureMode
  showFallback?: boolean
  /** Default on for elder-friendly coaching; user can mute. */
  voiceEnabled?: boolean
}>(), {
  mode: 'login',
  showFallback: true,
  voiceEnabled: true,
})

const emit = defineEmits<{
  captured: [frames: File[]]
  fallback: []
}>()

const video = ref<HTMLVideoElement | null>(null)
const capturing = ref(false)
const error = ref('')
const progress = ref('')
const stepIndex = ref(-1)
const countdown = ref(0)
const voiceOn = ref(props.voiceEnabled && isSpeechOutputSupported())
const voiceSupported = isSpeechOutputSupported()
let stream: MediaStream | null = null

const intro = computed(() => faceCaptureIntro(props.mode))
const activeStep = computed(() => (stepIndex.value >= 0 ? FACE_CAPTURE_STEPS[stepIndex.value] : null))
const overlayLabel = computed(() => {
  if (countdown.value > 0) return String(countdown.value)
  if (activeStep.value) return activeStep.value.title
  if (capturing.value) return '正在打开摄像头…'
  return '把脸放进圆圈'
})

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
  // Give slow speech time to finish before the next action; length-based floor.
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
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('CAMERA_UNAVAILABLE')
    await speakAndPause(intro.value.speech, 2200)

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

    const canvas = document.createElement('canvas')
    const width = Math.min(video.value.videoWidth, 960)
    const height = Math.round(width * (video.value.videoHeight / video.value.videoWidth))
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('CAMERA_UNAVAILABLE')

    const frames: File[] = []
    for (let index = 0; index < FACE_CAPTURE_STEPS.length; index += 1) {
      const step = FACE_CAPTURE_STEPS[index]
      stepIndex.value = index
      progress.value = `${faceStepLabel(index)}：${step.title}`
      await speakAndPause(`${faceStepLabel(index)}。${step.speech}`, 2600)
      await runCountdown(3)
      progress.value = `${faceStepLabel(index)}：正在拍照…`
      context.drawImage(video.value, 0, 0, width, height)
      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9))
      if (!blob) throw new Error('CAMERA_UNAVAILABLE')
      frames.push(new File([blob], `face-${props.mode}-${index + 1}.jpg`, { type: 'image/jpeg' }))
      if (index < FACE_CAPTURE_STEPS.length - 1) await wait(500)
    }

    progress.value = props.mode === 'registration'
      ? '采集完成，正在本地安全校验…'
      : '采集完成，正在识别，请稍等…'
    await speakAndPause(faceCaptureDoneSpeech(props.mode), 1200)
    emit('captured', frames)
  } catch (cause) {
    stopSpeaking()
    error.value = cause instanceof DOMException && cause.name === 'NotAllowedError'
      ? '摄像头权限被拒绝。请家人在浏览器地址栏点一下允许摄像头，或改用 PIN/密码登录。'
      : cause instanceof DOMException && cause.name === 'NotFoundError'
        ? '没有找到摄像头。请接好摄像头，或改用 PIN/密码登录。'
        : props.mode === 'registration'
          ? '摄像头打不开。请检查权限后重试，也可以让家人帮忙。'
          : '摄像头打不开或画面不好，请改用 PIN 登录，也可以让家人帮忙。'
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

onBeforeUnmount(() => {
  stopSpeaking()
  stopCamera()
})
</script>

<template>
  <div class="face-capture face-capture--elder" data-testid="face-video-capture">
    <div class="face-capture-intro">
      <p class="face-capture-intro-title">{{ intro.title }}</p>
      <ol class="face-capture-bullets">
        <li v-for="item in intro.bullets" :key="item">{{ item }}</li>
      </ol>
    </div>

    <div class="face-stage" :class="{ 'is-live': capturing }">
      <video
        ref="video"
        class="face-preview"
        muted
        playsinline
        aria-label="摄像头预览，请把脸放进中间圆圈"
      />
      <div class="face-guide" aria-hidden="true">
        <div class="face-guide-oval" />
        <div class="face-guide-crosshair" />
      </div>
      <div class="face-stage-banner" role="status" aria-live="polite">
        <strong>{{ overlayLabel }}</strong>
        <span v-if="activeStep">{{ activeStep.hint }}</span>
        <span v-else-if="!capturing">坐稳后点下面的大按钮开始</span>
      </div>
      <div class="face-step-dots" aria-hidden="true">
        <i
          v-for="(_, index) in FACE_CAPTURE_STEPS"
          :key="index"
          :class="{
            done: stepIndex > index,
            current: stepIndex === index,
          }"
        />
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
        {{ capturing ? '请按提示做，不要走开' : mode === 'registration' ? '开始录入（有语音提示）' : '开始刷脸（有语音提示）' }}
      </button>
      <button
        v-if="voiceSupported"
        type="button"
        class="btn btn-ghost btn-small"
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
        使用 PIN 登录
      </button>
    </div>
    <p class="face-capture-footnote">
      画面只在本机内存里处理，不会上传人脸照片。听不清或不会操作时，请点“使用 PIN 登录”，让家人帮忙也可以。
    </p>
  </div>
</template>
