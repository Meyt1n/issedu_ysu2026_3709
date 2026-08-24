/**
 * MOB-149：短视频录入的本地校验。
 *
 * 上传前先在本地校验格式、时长、大小和方向，并给出“将上传的媒体”摘要；
 * 不支持或超限时不得上传。上限镜像服务端默认契约（HCT-414-D2：
 * max_upload_bytes = 10 MiB、vision_video_max_duration_seconds = 30s），
 * 服务端仍是最终事实，本地拦截只是为了不发起注定失败的上传。
 */

export const VIDEO_ALLOWED_EXTENSIONS = ['.mp4', '.mov'] as const
export const VIDEO_ALLOWED_MIME_TYPES = ['video/mp4', 'video/quicktime', 'video/x-quicktime'] as const
/** 与服务端 Settings.max_upload_bytes 默认值保持一致。 */
export const VIDEO_MAX_BYTES = 10 * 1024 * 1024
/** 与服务端 vision_video_max_duration_seconds 默认值保持一致。 */
export const VIDEO_MAX_DURATION_SECONDS = 30

export interface VideoProbe {
  durationSeconds: number
  width: number
  height: number
}

export interface VideoValidation {
  ok: boolean
  message: string
  /** 通过校验后展示的“将上传”摘要；未通过时为空。 */
  summary: string
}

export function formatByteSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** 读取视频元数据（时长/分辨率）；解析失败按 fail-closed 处理。 */
export function probeVideoFile(file: File, timeoutMs = 5000): Promise<VideoProbe> {
  return new Promise(resolve => {
    const url = URL.createObjectURL(file)
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.muted = true
    const done = (probe: VideoProbe | null) => {
      clearTimeout(timer)
      video.removeAttribute('src')
      URL.revokeObjectURL(url)
      resolve(probe ?? { durationSeconds: 0, width: 0, height: 0 })
    }
    const timer = setTimeout(() => done(null), timeoutMs)
    video.onloadedmetadata = () => {
      done({
        durationSeconds: Number.isFinite(video.duration) ? video.duration : 0,
        width: video.videoWidth || 0,
        height: video.videoHeight || 0,
      })
    }
    video.onerror = () => done(null)
    video.src = url
  })
}

export function validateMedicineVideo(file: File, probe: VideoProbe): VideoValidation {
  const name = file.name.toLowerCase()
  const extension = name.slice(name.lastIndexOf('.'))
  if (!(VIDEO_ALLOWED_EXTENSIONS as readonly string[]).includes(extension)) {
    return {
      ok: false,
      message: `仅支持 ${VIDEO_ALLOWED_EXTENSIONS.join(' / ')} 格式的短视频，已选择 ${extension || '未知格式'}；不会上传该文件。`,
      summary: '',
    }
  }
  if (!(VIDEO_ALLOWED_MIME_TYPES as readonly string[]).includes(file.type)) {
    return {
      ok: false,
      message: `视频类型“${file.type || '未知'}”不受支持；请使用手机默认相机录制的 MP4 / MOV 视频。`,
      summary: '',
    }
  }
  if (file.size > VIDEO_MAX_BYTES) {
    return {
      ok: false,
      message: `视频大小 ${formatByteSize(file.size)} 超过上限 ${formatByteSize(VIDEO_MAX_BYTES)}；请录制更短的片段后重试。`,
      summary: '',
    }
  }
  if (probe.durationSeconds <= 0 || probe.width <= 0 || probe.height <= 0) {
    return {
      ok: false,
      message: '无法读取视频时长或画面尺寸（可能是浏览器不支持的编码）；为避免无效上传，请换用 MP4 (H.264) 格式重试。',
      summary: '',
    }
  }
  if (probe.durationSeconds > VIDEO_MAX_DURATION_SECONDS) {
    return {
      ok: false,
      message: `视频时长 ${probe.durationSeconds.toFixed(1)} 秒超过上限 ${VIDEO_MAX_DURATION_SECONDS} 秒；请截短后重试。`,
      summary: '',
    }
  }
  const orientation = probe.height >= probe.width ? '竖屏' : '横屏'
  const extensionLabel = extension === '.mov' ? 'MOV' : 'MP4'
  return {
    ok: true,
    message: '',
    summary: `将上传：短视频（${extensionLabel}，${probe.durationSeconds.toFixed(1)} 秒，${formatByteSize(file.size)}，${orientation}）`,
  }
}

export function videoInputUnavailableMessage(): string {
  return '当前浏览器或 WebView 不支持视频文件选择；请使用图片拍摄，或在支持视频采集的设备上使用短视频录入。'
}
