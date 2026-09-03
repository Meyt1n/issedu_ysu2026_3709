/**
 * 展演能力已并入普通模式（HCT-533）：启动仪式登录后每次会话播放一次，
 * 守护光球常驻，不再有独立的「展演模式」开关。本模块只保留状态映射纯函数。
 */
export const SHOWCASE_BOOT_PHASES = [
  { key: 'init', label: 'INITIALIZING HOMECARE TWIN', hint: '视觉演示层' },
  { key: 'graph', label: 'CONNECTING FAMILY GRAPH', hint: '关系投影' },
  { key: 'local', label: 'LOADING LOCAL AI', hint: '本地能力' },
  { key: 'privacy', label: 'PRIVACY SHIELD', hint: '本地可信域' },
  { key: 'ready', label: 'SYSTEM READY', hint: '展示空间已就绪' },
] as const

export type ShowcaseBootPhaseState = 'complete' | 'active' | 'pending'

export function bootPhaseState(index: number, activeIndex: number): ShowcaseBootPhaseState {
  if (index < activeIndex) return 'complete'
  if (index === activeIndex) return 'active'
  return 'pending'
}

export type GuardianState = 'idle' | 'loading' | 'scanning' | 'assistant' | 'attention' | 'offline'

export interface GuardianContext {
  sessionStatus: string
  currentView: string
  loadingScope: boolean
  pendingReviewCount: number
}

export function guardianStateFor(context: GuardianContext): GuardianState {
  if (context.sessionStatus !== 'ready') return 'offline'
  if (context.loadingScope) return 'loading'
  if (context.currentView === 'scan') return 'scanning'
  if (context.currentView === 'assistant') return 'assistant'
  if (context.pendingReviewCount > 0) return 'attention'
  return 'idle'
}

export type RadarStage = 'idle' | 'queued' | 'analyzing' | 'review' | 'error'

export function radarStageFor(status: string, hasResult = false): RadarStage {
  if (status === 'queued') return 'queued'
  if (status === 'running') return 'analyzing'
  if (status === 'succeeded' && hasResult) return 'review'
  if (status === 'failed' || status === 'timeout') return 'error'
  return 'idle'
}
