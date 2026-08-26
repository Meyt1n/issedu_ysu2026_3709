import { describe, expect, it } from 'vitest'

import {
  crossPortalUrl,
  MEMBER_PORTAL_ENTRY_STEPS,
  portalEntryBranding,
  portalEntryConflict,
  portalEntryConflictNotice,
  resolvePortalEntryMode,
} from './portalEntry'

describe('resolvePortalEntryMode (HCT-453)', () => {
  it('defaults to auto when nothing is configured', () => {
    expect(resolvePortalEntryMode({})).toBe('auto')
    expect(resolvePortalEntryMode({ port: '5173' })).toBe('auto')
    expect(resolvePortalEntryMode({ port: '8080' })).toBe('auto')
  })

  it('prefers the explicit query override over everything else', () => {
    expect(
      resolvePortalEntryMode({
        queryPortal: 'admin',
        defineMode: 'member',
        injectedMode: 'member',
        port: '5173',
      }),
    ).toBe('admin')
    expect(resolvePortalEntryMode({ queryPortal: 'member', port: '5174' })).toBe('member')
  })

  it('uses the build/dev define before the nginx injection', () => {
    expect(resolvePortalEntryMode({ defineMode: 'member', injectedMode: 'admin' })).toBe('member')
    expect(resolvePortalEntryMode({ injectedMode: 'admin' })).toBe('admin')
  })

  it('falls back to known admin entry ports only', () => {
    expect(resolvePortalEntryMode({ port: '5174' })).toBe('admin')
    expect(resolvePortalEntryMode({ port: '8081' })).toBe('admin')
    expect(resolvePortalEntryMode({ port: '5184' })).toBe('admin')
    expect(resolvePortalEntryMode({ port: '3000' })).toBe('auto')
  })

  it('ignores unknown values instead of guessing', () => {
    expect(resolvePortalEntryMode({ queryPortal: 'root', defineMode: 'ADMIN' })).toBe('auto')
    expect(resolvePortalEntryMode({ injectedMode: 42 })).toBe('auto')
  })
})

describe('portalEntryConflict', () => {
  it('never blocks the auto entry (legacy single-entry behaviour)', () => {
    expect(portalEntryConflict('auto', 'member')).toBeNull()
    expect(portalEntryConflict('auto', 'admin')).toBeNull()
  })

  it('accepts a matching entry and portal', () => {
    expect(portalEntryConflict('member', 'member')).toBeNull()
    expect(portalEntryConflict('admin', 'admin')).toBeNull()
  })

  it('sends an owner on the member entry to the admin entry', () => {
    expect(portalEntryConflict('member', 'admin')).toBe('need-admin-entry')
  })

  it('sends a plain member on the admin entry back to the member entry', () => {
    expect(portalEntryConflict('admin', 'member')).toBe('need-member-entry')
  })
})

describe('crossPortalUrl', () => {
  const noEnv = { memberUrl: null, adminUrl: null }

  it('prefers explicitly configured public urls and adds the portal override', () => {
    expect(
      crossPortalUrl('admin', { protocol: 'http:', hostname: 'localhost', port: '5173' }, {
        memberUrl: null,
        adminUrl: 'https://admin.example.test/',
      }),
    ).toBe('https://admin.example.test/?portal=admin')
  })

  it('keeps an already-present portal override on configured urls untouched', () => {
    expect(
      crossPortalUrl('member', { protocol: 'http:', hostname: 'localhost', port: '5174' }, {
        memberUrl: 'https://family.example.test/?portal=member',
        adminUrl: null,
      }),
    ).toBe('https://family.example.test/?portal=member')
  })

  it('swaps the vite dev ports 5173/5174 with an explicit portal override', () => {
    expect(
      crossPortalUrl('admin', { protocol: 'http:', hostname: '127.0.0.1', port: '5173' }, noEnv),
    ).toBe('http://127.0.0.1:5174/?portal=admin')
    expect(
      crossPortalUrl('member', { protocol: 'http:', hostname: '127.0.0.1', port: '5174' }, noEnv),
    ).toBe('http://127.0.0.1:5173/?portal=member')
  })

  it('swaps the compose ports 8080/8081 with an explicit portal override', () => {
    expect(
      crossPortalUrl('admin', { protocol: 'http:', hostname: 'localhost', port: '8080' }, noEnv),
    ).toBe('http://localhost:8081/?portal=admin')
    expect(
      crossPortalUrl('member', { protocol: 'http:', hostname: 'localhost', port: '8081' }, noEnv),
    ).toBe('http://localhost:8080/?portal=member')
  })

  it('swaps the local demo ports 5183/5184 with an explicit portal override', () => {
    expect(
      crossPortalUrl('admin', { protocol: 'http:', hostname: '127.0.0.1', port: '5183' }, noEnv),
    ).toBe('http://127.0.0.1:5184/?portal=admin')
    expect(
      crossPortalUrl('member', { protocol: 'http:', hostname: '127.0.0.1', port: '5184' }, noEnv),
    ).toBe('http://127.0.0.1:5183/?portal=member')
  })

  it('returns empty for unknown ports so the UI can degrade to text', () => {
    expect(
      crossPortalUrl('admin', { protocol: 'https:', hostname: 'family.lan', port: '443' }, noEnv),
    ).toBe('')
    expect(crossPortalUrl('admin', null, noEnv)).toBe('')
  })
})

describe('portalEntryBranding', () => {
  it('keeps the legacy welcome page for the auto entry', () => {
    expect(portalEntryBranding('auto')).toBeNull()
  })

  it('brands the member entry as a personal front door around face/PIN', () => {
    const branding = portalEntryBranding('member')!
    expect(branding.formTitle).toContain('我的健康日常')
    expect(branding.heroTitle).toContain('我的健康日常')
    expect(branding.formIdentityHint).toContain('自己的身份')
    expect(branding.credentialOrder[0]).toBe('face')
    expect(branding.defaultCredential).toBe('pin')
    expect(branding.passwordBehindOtherWays).toBe(true)
    expect(branding.ctaLabel).toBe('进入我的前台')
    expect(branding.crossLinkTarget).toBe('admin')
  })

  it('brands the admin entry around whole-family management with password first', () => {
    const branding = portalEntryBranding('admin')!
    expect(branding.formTitle).toContain('家庭管理后台')
    expect(branding.formIdentityHint).toContain('整个家庭')
    expect(branding.credentialOrder[0]).toBe('password')
    expect(branding.credentialOrder).toEqual(['password'])
    expect(branding.defaultCredential).toBe('password')
    expect(branding.passwordBehindOtherWays).toBe(false)
    expect(branding.ctaLabel).toBe('进入管理后台')
    expect(branding.crossLinkTarget).toBe('member')
  })

  it('gives the two entries different rail copy so they cannot look alike', () => {
    const member = portalEntryBranding('member')!
    const admin = portalEntryBranding('admin')!
    expect(member.heroTitle).not.toBe(admin.heroTitle)
    expect(member.badge).not.toBe(admin.badge)
    expect(member.ctaLabel).not.toBe(admin.ctaLabel)
    const memberChipTexts = member.chips.map(chip => chip.text)
    for (const chip of admin.chips) {
      expect(memberChipTexts).not.toContain(chip.text)
    }
  })
})

describe('portalEntryConflictNotice', () => {
  it('explains the member-entry block and links to the admin entry', () => {
    const notice = portalEntryConflictNotice('need-admin-entry')
    expect(notice.message).toContain('家庭成员前台')
    expect(notice.message).toContain('管理员')
    expect(notice.message).toContain('grandma-demo')
    expect(notice.crossLinkTarget).toBe('admin')
  })

  it('explains creating a household on the member entry then switching to admin', () => {
    const notice = portalEntryConflictNotice('need-admin-entry', { afterCreate: true })
    expect(notice.message).toContain('家庭已创建')
    expect(notice.message).toContain('管理后台')
    expect(notice.crossLinkTarget).toBe('admin')
  })

  it('explains the admin-entry block and links back to the member entry', () => {
    const notice = portalEntryConflictNotice('need-member-entry')
    expect(notice.message).toContain('管理后台')
    expect(notice.message).toContain('成员前台')
    expect(notice.message).toContain('web-member')
    expect(notice.crossLinkTarget).toBe('member')
  })

  it('lists the three steps for entering the member portal', () => {
    expect(MEMBER_PORTAL_ENTRY_STEPS).toHaveLength(3)
    expect(MEMBER_PORTAL_ENTRY_STEPS[0]).toContain('web-member')
    expect(MEMBER_PORTAL_ENTRY_STEPS[1]).toContain('5173')
    expect(MEMBER_PORTAL_ENTRY_STEPS[2]).toContain('demo-parent')
  })
})
