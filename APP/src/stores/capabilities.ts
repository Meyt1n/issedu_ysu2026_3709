import { reactive } from 'vue'

import type { CapabilityResponse } from '@/api/types'

/** 能力探测只在当前运行时有效，绝不写入 localStorage，避免把过期权限当成现状。 */
export interface CapabilitySnapshot {
  phase: string
  available: string[]
  unavailable: string[]
}

export const CAPABILITY_IDS = {
  manualHealthEvent: 'manual-health-event',
  householdMember: 'household-member',
  fieldAuthorization: 'field-authorization',
  auditOutbox: 'audit-outbox',
  eventCompensationReplay: 'event-compensation-replay',
  outboxRecoveryWorker: 'outbox-recovery-worker',
  reviewTask: 'review-task',
  visionTask: 'vision-task',
  visionInference: 'vision-inference',
  knowledgeStore: 'knowledge-store',
  localAssistant: 'local-assistant',
  llm: 'llm',
  llmCloud: 'llm-cloud',
  externalWeb: 'external-web',
  riskAcknowledgement: 'risk-acknowledgement',
} as const

export type CapabilityId = (typeof CAPABILITY_IDS)[keyof typeof CAPABILITY_IDS] | (string & {})

interface CapabilityMeta {
  label: string
  description: string
}

const CAPABILITY_META: Record<string, CapabilityMeta> = {
  [CAPABILITY_IDS.manualHealthEvent]: { label: '手工健康事件', description: '记录经确认的家庭健康事实。' },
  [CAPABILITY_IDS.householdMember]: { label: '家庭与成员', description: '读取当前身份可访问的家庭和成员。' },
  [CAPABILITY_IDS.fieldAuthorization]: { label: '字段授权', description: '按授权范围过滤可见健康字段。' },
  [CAPABILITY_IDS.auditOutbox]: { label: '审计与事件投递', description: '保留可追溯的审计事件投递记录。' },
  [CAPABILITY_IDS.eventCompensationReplay]: { label: '事件补偿重放', description: '支持失败事件的补偿与重放。' },
  [CAPABILITY_IDS.outboxRecoveryWorker]: { label: '投递恢复任务', description: '后台恢复未完成的事件投递。' },
  [CAPABILITY_IDS.reviewTask]: { label: '人工复核任务', description: '创建并跟踪需要人工确认的复核任务。' },
  [CAPABILITY_IDS.visionTask]: { label: '视觉任务', description: '提交照片并创建视觉识别任务。' },
  [CAPABILITY_IDS.visionInference]: { label: '视觉推理', description: '在服务端执行视觉模型推理。' },
  [CAPABILITY_IDS.knowledgeStore]: { label: '知识库', description: '访问受边界约束的家庭知识内容。' },
  [CAPABILITY_IDS.localAssistant]: { label: '本地助手', description: '使用家庭可信域内的助手能力。' },
  [CAPABILITY_IDS.llm]: { label: '语言模型', description: '提供受约束的语言模型能力。' },
  [CAPABILITY_IDS.llmCloud]: { label: '云端语言模型', description: '访问外部云端语言模型服务。' },
  [CAPABILITY_IDS.externalWeb]: { label: '外部网络', description: '访问家庭可信域之外的网络服务。' },
  [CAPABILITY_IDS.riskAcknowledgement]: { label: '风险知晓回写', description: '把“我已知晓”状态写回家庭服务器。' },
}

const state = reactive<{ snapshot: CapabilitySnapshot | null }>({ snapshot: null })

function cleanIds(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return [...new Set(value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).map(item => item.trim()))]
}

/** 对服务端能力列表做去重和冲突收敛；冲突时 unavailable 优先，默认 fail-closed。 */
export function normalizeCapabilities(response: Partial<CapabilityResponse> | null | undefined): CapabilitySnapshot {
  const unavailable = cleanIds(response?.unavailable)
  const unavailableSet = new Set(unavailable)
  return {
    phase: typeof response?.phase === 'string' && response.phase.trim() ? response.phase.trim() : 'unknown',
    available: cleanIds(response?.available).filter(id => !unavailableSet.has(id)),
    unavailable,
  }
}

export function capabilityLabel(id: string): string {
  return CAPABILITY_META[id]?.label ?? `未识别能力（${id}）`
}

export function capabilityDescription(id: string): string {
  return CAPABILITY_META[id]?.description ?? '服务端未提供该能力的说明，应用不会据此推断可用功能。'
}

export function setCapabilities(response: Partial<CapabilityResponse>): CapabilitySnapshot {
  const snapshot = normalizeCapabilities(response)
  state.snapshot = snapshot
  return snapshot
}

export function clearCapabilities(): void {
  state.snapshot = null
}

/** 只有服务端明确声明 available 且未同时列入 unavailable 才返回 true。 */
export function hasCapability(id: string): boolean {
  return Boolean(state.snapshot?.available.includes(id))
}

export function useCapabilities() {
  return { capabilities: state, setCapabilities, clearCapabilities, hasCapability }
}
