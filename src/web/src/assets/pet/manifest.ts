export const COMPANION_PET_STATES = [
  'idle',
  'blink',
  'wave',
  'happy',
  'cheer',
  'think',
  'shy',
  'sleep',
  'loading',
  'point',
  'listening',
  'reminder',
  'success',
] as const

export type CompanionPetState = (typeof COMPANION_PET_STATES)[number]
export type CompanionPetSize = 'small' | 'medium' | 'large'
export type CompanionPetPlacement = 'inline' | 'floating' | 'card' | 'empty'

export interface CompanionPetAnimation {
  frames: number
  frameMs: number
  loop: boolean
  label: string
}

export const COMPANION_PET_ANIMATIONS: Record<CompanionPetState, CompanionPetAnimation> = {
  idle: { frames: 6, frameMs: 360, loop: true, label: '安静陪伴' },
  blink: { frames: 4, frameMs: 110, loop: false, label: '眨眨眼' },
  wave: { frames: 6, frameMs: 130, loop: false, label: '挥手欢迎' },
  happy: { frames: 4, frameMs: 180, loop: false, label: '开心回应' },
  cheer: { frames: 6, frameMs: 130, loop: false, label: '为你鼓励' },
  think: { frames: 6, frameMs: 260, loop: true, label: '认真思考' },
  shy: { frames: 4, frameMs: 210, loop: false, label: '温柔鼓励' },
  sleep: { frames: 6, frameMs: 420, loop: true, label: '安静休息' },
  loading: { frames: 6, frameMs: 240, loop: true, label: '正在准备' },
  point: { frames: 6, frameMs: 180, loop: true, label: '为你引导' },
  listening: { frames: 6, frameMs: 260, loop: true, label: '正在倾听' },
  reminder: { frames: 6, frameMs: 220, loop: true, label: '轻声提醒' },
  success: { frames: 6, frameMs: 140, loop: false, label: '已经完成' },
}

/**
 * 真实逐帧资源清单。后续素材到位时按状态填入 URL；数组为空时，
 * CompanionPet 会使用同一套轮廓规范的内置 SVG 离散帧，不发起无效请求。
 */
export const COMPANION_PET_FRAME_SOURCES: Partial<Record<CompanionPetState, readonly string[]>> = {}

export function companionPetFrameCount(state: CompanionPetState): number {
  return COMPANION_PET_FRAME_SOURCES[state]?.length || COMPANION_PET_ANIMATIONS[state].frames
}

export function companionPetDuration(state: CompanionPetState): number {
  return companionPetFrameCount(state) * COMPANION_PET_ANIMATIONS[state].frameMs
}

export function normalizeCompanionPetFrame(frame: number, frameCount: number): number {
  if (frameCount <= 1) return 0
  return ((Math.trunc(frame) % frameCount) + frameCount) % frameCount
}
