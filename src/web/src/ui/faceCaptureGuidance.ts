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

/** Registration keeps a 3-frame multi-angle sequence. */
export const FACE_CAPTURE_REGISTRATION_STEPS: FaceCaptureStep[] = [
  {
    title: '请把脸放进圆圈中间',
    speech: '请把整张脸放进画面中间的圆圈里，眼睛看着镜头，保持大约半米远。',
    hint: '眼睛看镜头 · 距离大约半米 · 光线尽量均匀',
  },
  {
    title: '很好，头轻轻向左转一点',
    speech: '很好。请把脑袋轻轻向左边转一点点，脸还要留在圆圈里。',
    hint: '慢慢转，不要离开圆圈',
  },
  {
    title: '最后一步，头轻轻向右转一点',
    speech: '最后一步。请把脑袋轻轻向右边转一点点，然后看着镜头。',
    hint: '转完后看镜头，马上拍第三张',
  },
]

/** Login uses a shorter 2-frame path (API still accepts 2–3). */
export const FACE_CAPTURE_LOGIN_STEPS: FaceCaptureStep[] = [
  {
    title: '请把脸放进圆圈中间',
    speech: '请把整张脸放进圆圈里，眼睛看着镜头。',
    hint: '眼睛看镜头 · 光线均匀',
  },
  {
    title: '头轻轻转一点',
    speech: '很好。请把头轻轻向一边转一点点，脸还要留在圆圈里。',
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
      speech: '我们一起录入人脸。请坐稳，把脸放进圆圈，听语音提示慢慢转头。不会上传照片，也可以随时改用数字密码。',
      bullets: [
        '请坐到光线明亮、正对摄像头的位置',
        '把整张脸放进中间圆圈，不要太近也不要太远',
        '听到提示后再慢慢转头，一共拍三张',
        '不会了可以点“改用数字密码”，家人可以帮忙',
      ],
    }
  }
  return {
    title: '刷脸进入',
    speech: '请把脸放进圆圈，听提示轻轻转一下头。也可以改用数字密码。',
    bullets: [
      '把脸放进中间圆圈，看着镜头',
      '听到提示后轻轻转一下头',
      '拍完两张会自动继续',
      '不方便时请点“改用数字密码”',
    ],
  }
}

export function faceCaptureCountdownSpeech(seconds: number): string {
  return `${seconds}，`
}

export function faceCaptureDoneSpeech(mode: FaceCaptureMode): string {
  return mode === 'registration'
    ? '采集完成，正在本地安全校验，请稍等。'
    : '采集完成，正在识别，请稍等。'
}

export function faceStepLabel(index: number, total = 3): string {
  return `第 ${index + 1} 步，共 ${total} 步`
}

export function faceCaptureStartLabel(mode: FaceCaptureMode): string {
  return mode === 'registration' ? '开始录入（有语音提示）' : '刷脸进入'
}
