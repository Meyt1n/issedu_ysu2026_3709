<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{
  captured: [frames: File[]]
  fallback: []
}>()

const video = ref<HTMLVideoElement | null>(null)
const capturing = ref(false)
const error = ref('')
let stream: MediaStream | null = null

function stopCamera(): void {
  for (const track of stream?.getTracks() ?? []) track.stop()
  stream = null
  if (video.value) video.value.srcObject = null
}

function wait(milliseconds: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, milliseconds))
}

async function capture(): Promise<void> {
  if (props.disabled || capturing.value) return
  error.value = ''
  capturing.value = true
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('CAMERA_UNAVAILABLE')
    stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
    if (!video.value) throw new Error('CAMERA_UNAVAILABLE')
    video.value.srcObject = stream
    await video.value.play()
    await wait(250)

    const canvas = document.createElement('canvas')
    const width = Math.min(video.value.videoWidth || 640, 640)
    const height = Math.round(width * (video.value.videoHeight / (video.value.videoWidth || width))) || 480
    canvas.width = width
    canvas.height = height
    const frames: File[] = []
    for (let index = 0; index < 3; index += 1) {
      const context = canvas.getContext('2d')
      if (!context) throw new Error('CAMERA_UNAVAILABLE')
      context.drawImage(video.value, 0, 0, width, height)
      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.86))
      if (!blob) throw new Error('CAMERA_UNAVAILABLE')
      frames.push(new File([blob], `face-frame-${index + 1}.jpg`, { type: 'image/jpeg' }))
      if (index < 2) await wait(300)
    }
    emit('captured', frames)
  } catch (cause) {
    error.value = cause instanceof DOMException && cause.name === 'NotAllowedError'
      ? '摄像头权限被拒绝，请改用 PIN 登录。'
      : '摄像头不可用或画面质量不足，请改用 PIN 登录。'
    emit('fallback')
  } finally {
    stopCamera()
    capturing.value = false
  }
}

onBeforeUnmount(stopCamera)
</script>

<template>
  <div class="face-capture">
    <video ref="video" class="face-preview" muted playsinline aria-label="摄像头预览" />
    <p class="form-sub">请保持正面并缓慢转动视线，系统会采集短暂的多帧活体序列。</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <div class="face-capture-actions">
      <button type="button" class="btn btn-primary" :disabled="disabled || capturing" @click="capture">
        {{ capturing ? '正在验证活体' : '开始摄像头验证' }}
      </button>
      <button type="button" class="btn btn-ghost btn-small" :disabled="capturing" @click="emit('fallback')">
        使用 PIN 登录
      </button>
    </div>
  </div>
</template>
