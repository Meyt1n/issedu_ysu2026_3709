import { describe, expect, it } from 'vitest'

import {
  bootPhaseState,
  guardianStateFor,
  radarStageFor,
  SHOWCASE_BOOT_PHASES,
} from './showcase'

describe('showcase state mapping', () => {
  it('keeps the boot sequence ordered and explicit', () => {
    expect(SHOWCASE_BOOT_PHASES).toHaveLength(5)
    expect(bootPhaseState(0, 2)).toBe('complete')
    expect(bootPhaseState(2, 2)).toBe('active')
    expect(bootPhaseState(4, 2)).toBe('pending')
  })

  it('maps the guardian to the current application state', () => {
    const base = {
      sessionStatus: 'ready',
      currentView: 'overview',
      loadingScope: false,
      pendingReviewCount: 0,
    }

    expect(guardianStateFor(base)).toBe('idle')
    expect(guardianStateFor({ ...base, currentView: 'scan' })).toBe('scanning')
    expect(guardianStateFor({ ...base, loadingScope: true })).toBe('loading')
    expect(guardianStateFor({ ...base, pendingReviewCount: 1 })).toBe('attention')
    expect(guardianStateFor({ ...base, sessionStatus: 'signed-out' })).toBe('offline')
  })

  it('never treats a queued or failed scan as a confirmed result', () => {
    expect(radarStageFor('queued')).toBe('queued')
    expect(radarStageFor('running')).toBe('analyzing')
    expect(radarStageFor('succeeded', true)).toBe('review')
    expect(radarStageFor('succeeded', false)).toBe('idle')
    expect(radarStageFor('failed')).toBe('error')
  })
})
