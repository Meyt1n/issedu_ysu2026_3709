import { describe, expect, it } from 'vitest'

import { faceBindingSummary, memberUnboundGate, autoEntryMayUseBoundFace } from './welcomeFaceBinding'

describe('welcomeFaceBinding (HCT-510)', () => {
  it('never shows the device binding card for password login', () => {
    expect(faceBindingSummary('password', '').visible).toBe(false)
    expect(faceBindingSummary('password', 'household-1', '爷爷奶奶家').visible).toBe(false)
  })

  it('never shows the device binding card for PIN login', () => {
    expect(faceBindingSummary('pin', '').visible).toBe(false)
    expect(faceBindingSummary('pin', 'household-1', '爷爷奶奶家').visible).toBe(false)
  })

  it('keeps the unbound face card as a bind reminder without offering PIN fallback', () => {
    const summary = faceBindingSummary('face', '   ')
    expect(summary.visible).toBe(true)
    expect(summary.bound).toBe(false)
    expect(summary.title).toContain('尚未绑定')
    expect(summary.detail).toContain('管理后台')
    expect(summary.fallbackLabel).toBe('')
  })

  it('shows the bound household name without extra explanation', () => {
    const summary = faceBindingSummary('face', 'household-1', '爷爷奶奶家')
    expect(summary.visible).toBe(true)
    expect(summary.bound).toBe(true)
    expect(summary.title).toBe('爷爷奶奶家')
    expect(summary.detail).toBe('')
    expect(summary.fallbackLabel).toBe('')
  })

  it('falls back to a local-only label when the bound household has no cached name', () => {
    const summary = faceBindingSummary('face', 'household-legacy')
    expect(summary.bound).toBe(true)
    expect(summary.title).toBe('已绑定本机家庭')
  })
})

describe('memberUnboundGate (HCT-511)', () => {
  it('blocks the member login page until this computer has a bound household', () => {
    const gate = memberUnboundGate('member', '')
    expect(gate.blocked).toBe(true)
    expect(gate.title).toBe('请先到管理后台')
    expect(gate.message).toContain('管理后台')
    expect(gate.ctaLabel).toBe('去管理后台登录')
  })

  it('opens the member page once a household is bound, even if admin is no longer online', () => {
    expect(memberUnboundGate('member', 'household-1').blocked).toBe(false)
  })

  it('opens the member page while capabilities are still pending, once bound', () => {
    expect(memberUnboundGate('member', 'household-1', {
      capabilitiesPending: true,
      readyInstanceId: 'boot-1',
      readyHouseholdId: 'household-1',
    }).blocked).toBe(false)
  })

  it('opens the member page without requiring a matching admin-ready instance', () => {
    expect(memberUnboundGate('member', 'household-1', {
      instanceId: 'boot-2',
      readyInstanceId: 'boot-1',
      readyHouseholdId: 'household-1',
    }).blocked).toBe(false)
  })

  it('opens the member page when admin-ready matches this household', () => {
    expect(memberUnboundGate('member', 'household-1', {
      readyHouseholdId: 'household-1',
    }).blocked).toBe(false)
  })

  it('opens the member page when binding matches this API process', () => {
    expect(memberUnboundGate('member', 'household-1', {
      instanceId: 'boot-2',
      readyInstanceId: 'boot-2',
      readyHouseholdId: 'household-1',
    }).blocked).toBe(false)
  })

  it('never blocks the admin or auto entries', () => {
    expect(memberUnboundGate('admin', '').blocked).toBe(false)
    expect(memberUnboundGate('auto', '').blocked).toBe(false)
  })
})

describe('autoEntryMayUseBoundFace (HCT-516)', () => {
  it('allows face on the auto entry once a household is bound', () => {
    expect(autoEntryMayUseBoundFace('household-1')).toBe(true)
  })

  it('keeps allowing face when admin-ready matches', () => {
    expect(autoEntryMayUseBoundFace('household-1', {
      readyHouseholdId: 'household-1',
    })).toBe(true)
  })
})
