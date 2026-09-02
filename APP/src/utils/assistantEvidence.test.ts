import { describe, expect, it } from 'vitest'

import type { AssistantCitation, EvidencePreview } from '@/api/types'
import {
  assistantCitationTitle,
  extraAssistantSources,
  MAX_ASSISTANT_CITATIONS,
  MAX_CITATION_TEXT_LENGTH,
  shouldShowAssistantNoEvidence,
  uniqueAssistantCitations,
} from './assistantEvidence'

function citation(overrides: Partial<AssistantCitation> = {}): AssistantCitation {
  return {
    document_id: 'doc-1',
    version: 'idx-2026-08-01',
    chunk_id: 'chunk-1',
    document_title: '用药说明书',
    text: '每日一次，随餐服用。',
    locator: '第 2 页',
    ...overrides,
  }
}

function preview(overrides: Partial<EvidencePreview> = {}): EvidencePreview {
  return {
    query_type: 'GENERAL',
    database_tools: [],
    knowledge_titles: [],
    knowledge_count: 0,
    external_count: 0,
    rule_tools: [],
    ...overrides,
  }
}

describe('assistant evidence citations', () => {
  it('keeps the index version returned with the answer', () => {
    const [only] = uniqueAssistantCitations([citation({ version: 'idx-2026-08-28' })])
    expect(only.version).toBe('idx-2026-08-28')
  })

  it('merges repeated citations of the same source chunk', () => {
    const result = uniqueAssistantCitations([citation(), citation(), citation()])
    expect(result).toHaveLength(1)
  })

  it('keeps different chunks and different versions of one document apart', () => {
    const result = uniqueAssistantCitations([
      citation(),
      citation({ chunk_id: 'chunk-2' }),
      citation({ version: 'idx-2026-07-01' }),
    ])
    expect(result).toHaveLength(3)
  })

  it('drops citations without a usable document or chunk identifier', () => {
    const result = uniqueAssistantCitations([
      citation({ document_id: '   ' }),
      citation({ chunk_id: '' }),
      null as unknown as AssistantCitation,
      citation({ chunk_id: 'chunk-ok' }),
    ])
    expect(result).toHaveLength(1)
    expect(result[0].chunk_id).toBe('chunk-ok')
  })

  it('bounds the citation count and the quoted text length', () => {
    const many = Array.from({ length: MAX_ASSISTANT_CITATIONS + 6 }, (_, index) =>
      citation({ chunk_id: `chunk-${index}` }),
    )
    expect(uniqueAssistantCitations(many)).toHaveLength(MAX_ASSISTANT_CITATIONS)

    const [long] = uniqueAssistantCitations([
      citation({ text: 'x'.repeat(MAX_CITATION_TEXT_LENGTH + 500) }),
    ])
    expect(long.text).toHaveLength(MAX_CITATION_TEXT_LENGTH)
  })

  it('treats missing citation lists as no evidence', () => {
    expect(uniqueAssistantCitations(null)).toEqual([])
    expect(uniqueAssistantCitations(undefined)).toEqual([])
  })
})

describe('assistant evidence extra sources', () => {
  it('hides source labels already shown as citation cards', () => {
    const cited = [citation()]
    expect(extraAssistantSources(['用药说明书', 'doc-1', 'chunk-1'], cited)).toEqual([])
  })

  it('keeps and de-duplicates sources with no citation card', () => {
    const result = extraAssistantSources(
      ['家庭护理手册', '家庭护理手册', '  ', '用药说明书'],
      [citation()],
    )
    expect(result).toEqual(['家庭护理手册'])
  })

  it('falls back to the document id when no title was returned', () => {
    expect(assistantCitationTitle(citation({ document_title: null }))).toBe('doc-1')
    expect(assistantCitationTitle(citation())).toBe('用药说明书')
  })
})

describe('assistant evidence empty-state', () => {
  it('shows an explicit empty state when the server preview has no knowledge or external evidence', () => {
    expect(shouldShowAssistantNoEvidence([], [], preview())).toBe(true)
  })

  it('keeps the empty state for a degraded answer even without a preview event', () => {
    expect(shouldShowAssistantNoEvidence([], [], null, true)).toBe(true)
  })

  it('does not call a fact source or a retrieved citation empty evidence', () => {
    expect(shouldShowAssistantNoEvidence([], ['event-1'], preview())).toBe(false)
    expect(shouldShowAssistantNoEvidence([citation()], [], preview())).toBe(false)
  })

  it('does not infer empty evidence when an older response has no preview metadata', () => {
    expect(shouldShowAssistantNoEvidence([], [])).toBe(false)
  })
})
