import { describe, expect, it } from 'vitest'

import type { ReviewTask } from '../api/types'
import { isSameLocalDay, memberEventCount, reviewDrugCandidate } from './overviewView'

const task: Pick<ReviewTask, 'selected_candidate' | 'manual_payload' | 'candidates'> = {
  selected_candidate: null,
  manual_payload: null,
  candidates: [{ drug_name: '阿莫西林胶囊', confidence: 0.96, evidence: ['OCR'] }],
}

describe('home overview projection helpers', () => {
  it('keeps recent scan candidates separate from confirmed facts', () => {
    expect(reviewDrugCandidate(task)).toBe('阿莫西林胶囊')
    expect(reviewDrugCandidate({ ...task, candidates: [] })).toBe('药品名称待确认')
  })

  it('prefers active facts and never returns a negative count', () => {
    expect(memberEventCount({ state: { active_event_count: 2, events_count: 9 } } as never)).toBe(2)
    expect(memberEventCount({ state: { events_count: -1 } } as never)).toBe(0)
    expect(memberEventCount(null)).toBe(0)
  })

  it('recognizes a plan scheduled for the current local day', () => {
    const now = new Date(2026, 7, 20, 10, 0, 0)
    expect(isSameLocalDay('2026-08-20T18:30:00', now)).toBe(true)
    expect(isSameLocalDay('2026-08-21T00:00:00', now)).toBe(false)
    expect(isSameLocalDay('not-a-date', now)).toBe(false)
  })
})
