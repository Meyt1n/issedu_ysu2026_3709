import { describe, expect, it } from 'vitest'

import { faceBindingSummary } from './welcomeFaceBinding'

describe('welcomeFaceBinding', () => {
  it('never shows the device binding card for password login', () => {
    expect(faceBindingSummary('password', '').visible).toBe(false)
    expect(faceBindingSummary('password', 'household-1', '爷爷奶奶家').visible).toBe(false)
  })

  it('never shows the device binding card for PIN login', () => {
    expect(faceBindingSummary('pin', '').visible).toBe(false)
    expect(faceBindingSummary('pin', 'household-1', '爷爷奶奶家').visible).toBe(false)
  })

  it('guides unbound face login to password entry and the face credential page', () => {
    const summary = faceBindingSummary('face', '   ')
    expect(summary.visible).toBe(true)
    expect(summary.bound).toBe(false)
    expect(summary.title).toContain('还没有开启人脸登录')
    expect(summary.detail).toContain('账号密码')
    expect(summary.detail).toContain('人脸凭证')
    expect(summary.fallbackLabel).toContain('账号密码')
  })

  it('shows the bound household name and the no-cross-household boundary', () => {
    const summary = faceBindingSummary('face', 'household-1', '爷爷奶奶家')
    expect(summary.visible).toBe(true)
    expect(summary.bound).toBe(true)
    expect(summary.title).toBe('爷爷奶奶家')
    expect(summary.detail).toContain('不会跨家搜索')
    expect(summary.fallbackLabel).toBe('')
  })

  it('falls back to a local-only label when the bound household has no cached name', () => {
    const summary = faceBindingSummary('face', 'household-legacy')
    expect(summary.bound).toBe(true)
    expect(summary.title).toBe('当前绑定家庭（仅在本机使用）')
  })
})
