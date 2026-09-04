import { describe, expect, it } from 'vitest'

import {
  COMPANION_PET_ANIMATIONS,
  COMPANION_PET_STATES,
  companionPetDuration,
  normalizeCompanionPetFrame,
} from './manifest'

describe('companion pet animation manifest', () => {
  it('defines every supported state with a usable animation', () => {
    expect(COMPANION_PET_STATES).toHaveLength(13)
    for (const state of COMPANION_PET_STATES) {
      expect(COMPANION_PET_ANIMATIONS[state].frames).toBeGreaterThanOrEqual(4)
      expect(companionPetDuration(state)).toBeGreaterThan(0)
    }
  })

  it('keeps frame indexes inside the active sequence', () => {
    expect(normalizeCompanionPetFrame(7, 6)).toBe(1)
    expect(normalizeCompanionPetFrame(-1, 6)).toBe(5)
    expect(normalizeCompanionPetFrame(4, 0)).toBe(0)
  })
})
