import { describe, expect, it } from 'vitest'

import { FORMAL_PASSWORD_HINT, formalPasswordMeetsPolicy } from './passwordPolicy'

describe('formalPasswordMeetsPolicy (HCT-512)', () => {
  it('accepts eight or more characters that mix English letters and digits', () => {
    expect(formalPasswordMeetsPolicy('password-123')).toBe(true)
    expect(formalPasswordMeetsPolicy('DemoOnly-ChangeMe1!')).toBe(true)
    expect(formalPasswordMeetsPolicy('Ab345678')).toBe(true)
  })

  it('rejects short, letter-only or digit-only passwords', () => {
    expect(formalPasswordMeetsPolicy('pass1')).toBe(false)
    expect(formalPasswordMeetsPolicy('password')).toBe(false)
    expect(formalPasswordMeetsPolicy('12345678')).toBe(false)
    expect(formalPasswordMeetsPolicy('DemoOnly-ChangeMe!')).toBe(false)
    expect(formalPasswordMeetsPolicy('密码12345678')).toBe(false)
  })

  it('keeps a family-facing hint that names both required character classes', () => {
    expect(FORMAL_PASSWORD_HINT).toContain('8')
    expect(FORMAL_PASSWORD_HINT).toContain('英文')
    expect(FORMAL_PASSWORD_HINT).toContain('数字')
  })
})
