import type { AssistantCitation } from '../api/types'

/**
 * HCT-450：助手回复元信息的展示逻辑。
 *
 * 之前聊天气泡下会同时堆出「问题类型 + 分流说明 + ⚠降级 + ⚠越权 + ⚠风险提示 +
 * 依据状态 + 逐条依据标识」，把有用的正文淹没在重复的警示里。这里把「显示什么、
 * 合并什么」的判断抽成纯函数，便于单测锁定行为。
 */

const QUESTION_TYPE_LABELS: Record<string, string> = {
  MEDICATION_SAFETY: '用药安全核对',
  SYMPTOM_MEDICATION: '症状用药资料解释',
  MEDICATION_RECORD: '用药记录查询',
  FAMILY_RECORD: '家庭健康档案查询',
  RULE_EVIDENCE: '规则与证据查询',
  URGENT: '紧急情况分流',
  GENERAL: '一般健康信息',
}

export function questionTypeLabel(queryType?: string | null): string {
  return QUESTION_TYPE_LABELS[queryType ?? ''] ?? '一般健康信息'
}

const CONFIDENCE_LABELS: Record<string, string> = {
  high: '较有把握',
  medium: '一般',
  low: '仅供参考',
}

export function confidenceLabel(confidence?: string | null): string {
  return CONFIDENCE_LABELS[confidence ?? ''] ?? '仅供参考'
}

/**
 * 问题类型与分流说明合并成一句人话。后端的 route_explanation 已经包含类型
 * 标签，重复展示「问题类型：X」只会增加噪音。
 */
export function routeSummary(
  queryType?: string | null,
  routeExplanation?: string | null,
): string | null {
  const explanation = routeExplanation?.trim()
  if (explanation) return explanation
  if (queryType) return `已按「${questionTypeLabel(queryType)}」处理这个问题`
  return null
}

/**
 * escalate 提示已经要求联系医生/药师，再叠加同义的 risk_notice 只是重复警告；
 * 仅在未升级时展示常规风险提示。
 */
export function visibleRiskNotice(
  escalate?: boolean,
  riskNotice?: string | null,
): string | null {
  if (escalate) return null
  return riskNotice?.trim() || null
}

/**
 * 已展开为引用卡片的 chunk_id 不再作为裸「依据标识」重复罗列，只保留
 * 事件/规则等无法展开的事实来源。
 */
export function extraFactSources(
  sources?: string[] | null,
  citations?: AssistantCitation[] | null,
): string[] {
  const cited = new Set((citations ?? []).map(citation => citation.chunk_id))
  return (sources ?? []).filter(source => source && !cited.has(source))
}

const MEDICATION_RECHECK_TYPES = new Set([
  'MEDICATION_SAFETY',
  'SYMPTOM_MEDICATION',
  'MEDICATION_RECORD',
  'DOSE_DECISION',
])

export function canRecheckMedicationSafety(queryType?: string | null): boolean {
  return MEDICATION_RECHECK_TYPES.has(queryType ?? '')
}
