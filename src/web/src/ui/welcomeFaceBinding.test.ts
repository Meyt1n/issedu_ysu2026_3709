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

  it('blocks the member page after a leftover household bind if admin is not logged in', () => {
    expect(memberUnboundGate('member', 'household-1').blocked).toBe(true)
  })

  it('blocks the member page until capabilities have been fetched', () => {
    expect(memberUnboundGate('member', 'household-1', {
      capabilitiesPending: true,
      readyInstanceId: 'boot-1',
      readyHouseholdId: 'household-1',
    }).blocked).toBe(true)
  })

  it('blocks the member page when this API process has no matching admin login', () => {
    const gate = memberUnboundGate('member', 'household-1', {
      instanceId: 'boot-2',
      readyInstanceId: 'boot-1',
      readyHouseholdId: 'household-1',
    })
    expect(gate.blocked).toBe(true)
    expect(gate.title).toBe('请先到管理后台')
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
  it('rejects leftover household binds when admin is not logged in', () => {
    expect(autoEntryMayUseBoundFace('household-1')).toBe(false)
  })

  it('allows face on the auto entry only when admin-ready matches', () => {
    expect(autoEntryMayUseBoundFace('household-1', {
      readyHouseholdId: 'household-1',
    })).toBe(true)
  })
})
