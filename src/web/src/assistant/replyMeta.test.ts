import { describe, expect, it } from 'vitest'

import type { AssistantCitation } from '../api/types'
import {
  canRecheckMedicationSafety,
  confidenceLabel,
  extraFactSources,
  questionTypeLabel,
  routeSummary,
  visibleRiskNotice,
} from './replyMeta'

describe('questionTypeLabel', () => {
  it('labels SYMPTOM_MEDICATION instead of falling back to GENERAL', () => {
    expect(questionTypeLabel('SYMPTOM_MEDICATION')).toBe('症状用药资料解释')
    expect(questionTypeLabel('MEDICATION_SAFETY')).toBe('用药安全核对')
    expect(questionTypeLabel('UNKNOWN_TYPE')).toBe('一般健康信息')
    expect(questionTypeLabel(null)).toBe('一般健康信息')
  })
})

describe('confidenceLabel', () => {
  it('translates the raw enum into user language', () => {
    expect(confidenceLabel('high')).toBe('较有把握')
    expect(confidenceLabel('medium')).toBe('一般')
    expect(confidenceLabel('low')).toBe('仅供参考')
    expect(confidenceLabel(undefined)).toBe('仅供参考')
  })
})

describe('routeSummary', () => {
  it('collapses type + explanation into one sentence', () => {
    expect(routeSummary('SYMPTOM_MEDICATION', '已按「症状用药资料解释」处理这个问题'))
      .toBe('已按「症状用药资料解释」处理这个问题')
  })

  it('falls back to the type label when no explanation is present', () => {
    expect(routeSummary('SYMPTOM_MEDICATION', null))
      .toBe('已按「症状用药资料解释」处理这个问题')
    expect(routeSummary(null, '   ')).toBeNull()
  })
})

describe('visibleRiskNotice', () => {
  it('hides the duplicate notice when the reply already escalates', () => {
    expect(visibleRiskNotice(true, '请咨询医生或药师')).toBeNull()
  })

  it('keeps the notice for non-escalated medication answers', () => {
    expect(visibleRiskNotice(false, '请咨询医生或药师')).toBe('请咨询医生或药师')
    expect(visibleRiskNotice(false, null)).toBeNull()
  })
})

describe('extraFactSources', () => {
  const citation: AssistantCitation = {
    document_id: 'doc-1',
    version: 'v1',
    chunk_id: 'chunk-1',
    document_title: '感冒样症状居家照护教学卡',
    text: '片段正文',
    locator: 'section:FAQ',
  }

  it('drops sources that are already rendered as citation cards', () => {
    expect(extraFactSources(['chunk-1', 'event-9'], [citation])).toEqual(['event-9'])
  })

  it('keeps all sources when nothing is cited', () => {
    expect(extraFactSources(['event-9'], [])).toEqual(['event-9'])
    expect(extraFactSources(undefined, undefined)).toEqual([])
  })
})

describe('canRecheckMedicationSafety', () => {
  it('only offers a medication recheck on medication-shaped turns', () => {
    expect(canRecheckMedicationSafety('MEDICATION_SAFETY')).toBe(true)
    expect(canRecheckMedicationSafety('SYMPTOM_MEDICATION')).toBe(true)
    expect(canRecheckMedicationSafety('GENERAL')).toBe(false)
    expect(canRecheckMedicationSafety(null)).toBe(false)
  })
})
