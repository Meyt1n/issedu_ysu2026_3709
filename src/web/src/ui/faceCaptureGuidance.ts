/** Elder-friendly face capture copy. Client-only; never sent as health facts. */

export type FaceCaptureMode = 'login' | 'registration'

export interface FaceCaptureStep {
  /** Short on-screen instruction (large text). */
  title: string
  /** Spoken instruction (slightly fuller, still simple Mandarin). */
  speech: string
  /** Small helper under the title. */
  hint: string
}

/**
 * 口播文案刻意保持一步一短句（不拼「第N步」，不加寒暄），
 * 由 FaceVideoCapture 播完一句再进入动作缓冲和倒计时，避免相互打断。
 */

/** Registration keeps a 3-frame multi-angle sequence. */
export const FACE_CAPTURE_REGISTRATION_STEPS: FaceCaptureStep[] = [
  {
    title: '请把脸放进圆圈中间',
    speech: '把脸放进圆圈，看着镜头。',
    hint: '眼睛看镜头 · 距离大约半米 · 光线尽量均匀',
  },
  {
    title: '很好，头轻轻向左转一点',
    speech: '头轻轻向左转一点。',
    hint: '慢慢转，不要离开圆圈',
  },
  {
    title: '最后一步，头轻轻向右转一点',
    speech: '再向右转一点，看镜头。',
    hint: '转完后看镜头，马上拍第三张',
  },
]

/** Login uses a shorter 2-frame path (API still accepts 2–3); 开场并入第 1 步。 */
export const FACE_CAPTURE_LOGIN_STEPS: FaceCaptureStep[] = [
  {
    title: '请把脸放进圆圈中间',
    speech: '把脸放进圆圈，看着镜头。',
    hint: '眼睛看镜头 · 光线均匀',
  },
  {
    title: '头轻轻转一点',
    speech: '头轻轻转一点。',
    hint: '轻轻转一下就好',
  },
]

/** @deprecated Prefer faceCaptureSteps(mode); kept for older imports. */
export const FACE_CAPTURE_STEPS = FACE_CAPTURE_REGISTRATION_STEPS

export function faceCaptureSteps(mode: FaceCaptureMode): FaceCaptureStep[] {
  return mode === 'registration' ? FACE_CAPTURE_REGISTRATION_STEPS : FACE_CAPTURE_LOGIN_STEPS
}

export function faceCaptureIntro(mode: FaceCaptureMode): { title: string; speech: string; bullets: string[] } {
  if (mode === 'registration') {
    return {
      title: '我们一起录入人脸，大约十几秒',
      speech: '开始录入，听提示慢慢做。',
      bullets: [
        '把脸放进圆圈，看着镜头',
        '听到提示后轻轻转头，拍三张',
      ],
    }
  }
  // 登录不再单独口播开场：说明已并入第 1 步口播；屏幕文案保留。
  return {
    title: '刷脸进入',
    speech: '',
    bullets: [
      '把脸放进圆圈，看着镜头',
      '听到提示后轻轻转一下头',
    ],
  }
}

export function faceCaptureCountdownSpeech(seconds: number): string {
  return `${seconds}，`
}

export function faceCaptureDoneSpeech(mode: FaceCaptureMode): string {
  return mode === 'registration'
    ? '好了，正在校验，请稍等。'
    : '好了，正在识别，请稍等。'
}

export function faceStepLabel(index: number, total = 3): string {
  return `第 ${index + 1} 步，共 ${total} 步`
}

export function faceCaptureStartLabel(mode: FaceCaptureMode): string {
  return mode === 'registration' ? '开始录入（有语音提示）' : '刷脸进入'
}
