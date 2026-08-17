import type { RecognitionStatus, RiskLevel, TaskLevel, TaskStatus } from './types'

export type Tone = 'danger' | 'warn' | 'info' | 'calm' | 'neutral'

/** 提醒四级（与主仓库需求 FR-05/FR-06 命名一致：INFO/GENERAL/HIGH/URGENT）。 */
export function taskLevelLabel(level: TaskLevel): string {
  switch (level) {
    case 'URGENT': return '紧急'
    case 'HIGH': return '重要'
    case 'GENERAL': return '一般'
    case 'INFO': return '信息'
    default: return '未分级'
  }
}

export function taskLevelTone(level: TaskLevel): Tone {
  switch (level) {
    case 'URGENT': return 'danger'
    case 'HIGH': return 'warn'
    case 'GENERAL': return 'info'
    case 'INFO': return 'neutral'
    default: return 'neutral'
  }
}

/** 风险四级（与主仓库 API RiskLevel 一致：SEVERE/WARNING/INFO/TIP）。 */
export function riskLevelLabel(level: RiskLevel): string {
  switch (level) {
    case 'SEVERE': return '严重'
    case 'WARNING': return '较高'
    case 'INFO': return '一般'
    case 'TIP': return '提示'
    default: return '未分级'
  }
}

export function riskLevelTone(level: RiskLevel): Tone {
  switch (level) {
    case 'SEVERE': return 'danger'
    case 'WARNING': return 'warn'
    case 'INFO': return 'info'
    case 'TIP': return 'calm'
    default: return 'neutral'
  }
}

/** 视觉识别四态（与主仓库 FR-03 一致：MATCHED/CONFLICT/UNKNOWN/REVIEW）。 */
export function recognitionStatusLabel(status: RecognitionStatus): string {
  switch (status) {
    case 'MATCHED': return '已匹配'
    case 'CONFLICT': return '证据冲突'
    case 'UNKNOWN': return '未知药品'
    case 'REVIEW': return '需人工复核'
    default: return '未知状态'
  }
}

export function recognitionStatusTone(status: RecognitionStatus): Tone {
  switch (status) {
    case 'MATCHED': return 'calm'
    case 'CONFLICT': return 'danger'
    case 'UNKNOWN': return 'warn'
    case 'REVIEW': return 'info'
    default: return 'neutral'
  }
}

export function taskStatusLabel(status: TaskStatus): string {
  switch (status) {
    case 'PENDING': return '待处理'
    case 'CONFIRMED': return '已确认'
    case 'DEFERRED': return '已延期'
    case 'SKIPPED': return '已跳过'
    case 'ESCALATED': return '已升级照护者'
    default: return '未知'
  }
}

export function eventStatusLabel(status: string): string {
  if (status === 'CONFIRMED') return '已确认'
  if (status === 'UNCONFIRMED') return '待确认'
  return status
}

export function memberRoleLabel(role: string): string {
  switch (role) {
    case 'SELF': return '本人'
    case 'DEPENDENT': return '被照护成员'
    case 'CAREGIVER': return '照护者'
    default: return role
  }
}
