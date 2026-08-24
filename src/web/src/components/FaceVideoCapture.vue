<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

const props = withDefaults(defineProps<{
  disabled?: boolean
  mode?: 'login' | 'registration'
  showFallback?: boolean
}>(), {
  mode: 'login',
  showFallback: true,
})

const emit = defineEmits<{
  captured: [frames: File[]]
  fallback: []
}>()

const video = ref<HTMLVideoElement | null>(null)
const capturing = ref(false)
const error = ref('')
const progress = ref('')
let stream: MediaStream | null = null

function stopCamera(): void {
  for (const track of stream?.getTracks() ?? []) track.stop()
  stream = null
  if (video.value) video.value.srcObject = null
}

function wait(milliseconds: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, milliseconds))
}

async function waitForVideoReady(element: HTMLVideoElement): Promise<void> {
  const deadline = Date.now() + 2500
  while (element.videoWidth <= 0 || element.videoHeight <= 0) {
    if (Date.now() >= deadline) throw new Error('CAMERA_NOT_READY')
    await wait(100)
  }
}

async function capture(): Promise<void> {
  if (props.disabled || capturing.value) return
  error.value = ''
  progress.value = '正在打开摄像头…'
  capturing.value = true
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('CAMERA_UNAVAILABLE')
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
    await wait(500)

    const canvas = document.createElement('canvas')
    const width = Math.min(video.value.videoWidth, 960)
    const height = Math.round(width * (video.value.videoHeight / video.value.videoWidth))
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('CAMERA_UNAVAILABLE')

    const frames: File[] = []
    for (let index = 0; index < 3; index += 1) {
      progress.value = `请保持一张脸在画面中央（正在采集 ${index + 1}/3）`
      context.drawImage(video.value, 0, 0, width, height)
      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9))
      if (!blob) throw new Error('CAMERA_UNAVAILABLE')
      frames.push(new File([blob], `face-${props.mode}-${index + 1}.jpg`, { type: 'image/jpeg' }))
      if (index < 2) await wait(500)
    }
    progress.value = '采集完成，正在提交本地安全校验…'
    emit('captured', frames)
  } catch (cause) {
    error.value = cause instanceof DOMException && cause.name === 'NotAllowedError'
      ? '摄像头权限被拒绝，请改用 PIN 登录。'
      : props.mode === 'registration'
        ? '摄像头不可用，请检查权限后重新采集。'
        : '摄像头不可用或画面质量不足，请改用 PIN 登录。'
    if (props.showFallback) emit('fallback')
  } finally {
    stopCamera()
    capturing.value = false
    progress.value = ''
  }
}

onBeforeUnmount(stopCamera)
</script>

<template>
  <div class="face-capture">
    <video ref="video" class="face-preview" muted playsinline aria-label="摄像头预览" />
    <p class="form-sub">
      {{ mode === 'registration'
        ? '请让本人看向镜头并缓慢转动头部，系统会采集三帧动态视频画面。视频只在本地内存中处理。'
        : '请保持正面并缓慢转动视线，系统会采集短暂的多帧活体序列。' }}
    </p>
    <p v-if="progress" class="notice" role="status" aria-live="polite">{{ progress }}</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <div class="face-capture-actions">
      <button type="button" class="btn btn-primary" :disabled="disabled || capturing" @click="capture">
        {{ capturing ? '正在采集动态画面' : mode === 'registration' ? '开始动态采集' : '开始摄像头验证' }}
      </button>
      <button v-if="showFallback" type="button" class="btn btn-ghost btn-small" :disabled="capturing" @click="emit('fallback')">
        使用 PIN 登录
      </button>
    </div>
  </div>
</template>
