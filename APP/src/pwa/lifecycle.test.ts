import { describe, expect, it } from 'vitest'
import { getPwaSupportSnapshot, isOwnedShellCache, isSafeStaticRequest } from './lifecycle'

describe('PWA lifecycle boundaries', () => {
  it('explains the ordinary web fallback when Service Worker is unavailable', () => {
    const support = getPwaSupportSnapshot(false, true)
    expect(support.capability).toBe('limited')
    expect(support.installPrompt).toBe(false)
  })
  it('offers an explicit install path only when the browser exposes it', () => {
    expect(getPwaSupportSnapshot(true, true).capability).toBe('installable')
    expect(getPwaSupportSnapshot(true, false).message).toContain('添加到主屏幕')
  })
  it('limits recovery to this application shell cache namespace', () => {
    expect(isOwnedShellCache('hct-mobile-shell-v2')).toBe(true)
    expect(isOwnedShellCache('third-party-cache')).toBe(false)
  })
  it('never considers API and health requests static cache candidates', () => {
    expect(isSafeStaticRequest(new URL('https://app.test/api/v1/today'), 'script')).toBe(false)
    expect(isSafeStaticRequest(new URL('https://app.test/assets/app.js'), 'script')).toBe(true)
  })
})
