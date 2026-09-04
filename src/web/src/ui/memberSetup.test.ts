import { describe, expect, it } from 'vitest'

import {
  canSubmitMemberSetup,
  memberSetupValidationMessage,
} from './memberSetup'

describe('member setup validation', () => {
  it('requires a display name', () => {
    expect(memberSetupValidationMessage('', 'grandma-1')).toBe('请填写家人称呼。')
  })

  it('rejects malformed account ids', () => {
    expect(memberSetupValidationMessage('奶奶', 'grandma 1')).toContain('登录名')
  })

  it('accepts a valid display name and account id', () => {
    expect(memberSetupValidationMessage(' 奶奶 ', ' grandma-1 ')).toBe('')
    expect(canSubmitMemberSetup(' 奶奶 ', ' grandma-1 ', false)).toBe(true)
    expect(canSubmitMemberSetup(' 奶奶 ', ' grandma-1 ', true)).toBe(false)
  })
})
