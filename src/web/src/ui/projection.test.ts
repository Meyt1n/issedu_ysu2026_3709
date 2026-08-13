import { describe, expect, it } from 'vitest'

import type { HealthEvent } from '../api/types'
import { buildFactsFromTimeline } from './projection'

function event(overrides: Partial<HealthEvent> & { id: string; event_type: string }): HealthEvent {
  return {
    household_id: 'household-1',
    member_id: 'member-1',
    sequence_no: 1,
    source: 'MANUAL',
    confirmation_status: 'CONFIRMED',
    payload: {},
    evidence: {},
    created_by: 'owner',
    confirmed_by: 'owner',
    idempotency_key: null,
    compensates_event_id: null,
    occurred_at: '2026-08-13T00:00:00Z',
    recorded_at: '2026-08-13T00:00:00Z',
    correlation_id: 'corr',
    causation_id: null,
    supersedes_event_id: null,
    schema_version: 1,
    created_at: '2026-08-13T00:00:00Z',
    ...overrides,
  }
}

describe('client-side member facts projection', () => {
  it('mirrors the backend relationship graph rules', () => {
    const facts = buildFactsFromTimeline([
      event({ id: 'e1', event_type: 'medication_added', payload: { drug: '阿司匹林肠溶片' } }),
      event({ id: 'e2', event_type: 'allergy_added', payload: { allergy: '青霉素' } }),
      event({ id: 'e3', event_type: 'disease_added', payload: { disease: '高血压' } }),
      event({ id: 'e4', event_type: 'plan_created', payload: { drug: '阿司匹林肠溶片', schedule: '每日一次' } }),
      event({ id: 'e5', event_type: 'allergy_removed', payload: { allergy: '青霉素' } }),
    ])

    expect(facts.drugs).toEqual([{ name: '阿司匹林肠溶片', addedBy: 'e1' }])
    expect(facts.allergies).toEqual([])
    expect(facts.diseases).toEqual([{ name: '高血压', addedBy: 'e3' }])
    expect(facts.plans).toEqual([
      { drug: '阿司匹林肠溶片', schedule: '每日一次', addedBy: 'e4' },
    ])
    expect(facts.eventsCount).toBe(5)
  })

  it('excludes compensated events from current facts', () => {
    const facts = buildFactsFromTimeline([
      event({ id: 'e1', event_type: 'medication_added', payload: { drug: '布洛芬缓释胶囊' } }),
      event({ id: 'e2', event_type: 'medication_added', payload: { drug: '硝苯地平缓释片' } }),
      event({
        id: 'e3',
        event_type: 'COMPENSATION',
        compensates_event_id: 'e1',
        payload: { original_event_type: 'medication_added' },
      }),
    ])

    expect(facts.drugs).toEqual([{ name: '硝苯地平缓释片', addedBy: 'e2' }])
  })
})
