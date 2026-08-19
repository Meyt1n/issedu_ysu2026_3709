import { beforeEach, describe, expect, it } from 'vitest'

import {
  CAPABILITY_IDS,
  capabilityDescription,
  capabilityLabel,
  clearCapabilities,
  hasCapability,
  normalizeCapabilities,
  setCapabilities,
} from './capabilities'

describe('capability probe state', () => {
  beforeEach(() => clearCapabilities())

  it('normalizes duplicate ids and lets unavailable win on conflicts', () => {
    expect(normalizeCapabilities({
      phase: ' P0-foundation ',
      available: ['vision-task', 'vision-task', 'risk-acknowledgement'],
      unavailable: ['risk-acknowledgement', 'risk-acknowledgement'],
    })).toEqual({
      phase: 'P0-foundation',
      available: ['vision-task'],
      unavailable: ['risk-acknowledgement'],
    })
  })

  it('fails closed until the server explicitly advertises a capability', () => {
    expect(hasCapability(CAPABILITY_IDS.visionTask)).toBe(false)
    setCapabilities({ phase: 'P0', available: ['vision-task'], unavailable: [] })
    expect(hasCapability(CAPABILITY_IDS.visionTask)).toBe(true)
    expect(hasCapability(CAPABILITY_IDS.riskAcknowledgement)).toBe(false)
    clearCapabilities()
    expect(hasCapability(CAPABILITY_IDS.visionTask)).toBe(false)
  })

  it('provides safe labels for known and unknown server ids', () => {
    expect(capabilityLabel(CAPABILITY_IDS.visionInference)).toBe('视觉推理')
    expect(capabilityDescription(CAPABILITY_IDS.visionInference)).toContain('视觉模型')
    expect(capabilityLabel('future-capability')).toContain('未识别能力')
    expect(capabilityDescription('future-capability')).toContain('不会据此推断')
  })
})
