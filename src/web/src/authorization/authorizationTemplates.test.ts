import { describe, expect, it } from 'vitest'

import type { Authorization } from '../api/types'
import {
  AUTHORIZATION_TEMPLATES,
  PURPOSE_OPTIONS,
  applyTemplate,
  auditActionLabel,
  auditOperationLabel,
  auditOutcomeLabel,
  auditReasonLabel,
  buildHandoffText,
  daysUntilExpiry,
  isExpiringSoon,
  purposeLabel,
} from './authorizationTemplates'

const SERVER_DATA_FIELDS = ['health_events', 'risk_alerts']
const SERVER_ACTIONS = ['READ_EVENTS', 'WRITE_EVENTS', 'ACK_RISK']
const PURPOSE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/

const baseAuthorization: Authorization = {
  id: 'authorization-1',
  household_id: 'household-1',
  member_id: 'member-1',
  grantor_actor_id: 'owner',
  grantee_actor_id: 'caregiver',
  data_fields: ['health_events'],
  actions: ['READ_EVENTS'],
  purpose: 'family-care',
  valid_from: '2026-08-01T00:00:00Z',
  valid_until: '2026-08-31T00:00:00Z',
  revoked_at: null,
  version: 1,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
}

describe('AUTHORIZATION_TEMPLATES', () => {
  it('provides between 2 and 4 family templates', () => {
    expect(AUTHORIZATION_TEMPLATES.length).toBeGreaterThanOrEqual(2)
    expect(AUTHORIZATION_TEMPLATES.length).toBeLessThanOrEqual(4)
  })

  it('never grants write access and stays inside server-supported fields/actions', () => {
    for (const template of AUTHORIZATION_TEMPLATES) {
      expect(template.actions).not.toContain('WRITE_EVENTS')
      for (const field of template.dataFields) {
        expect(SERVER_DATA_FIELDS).toContain(field)
      }
      for (const action of template.actions) {
        expect(SERVER_ACTIONS).toContain(action)
      }
      expect(template.dataFields.length).toBeGreaterThan(0)
      expect(template.actions.length).toBeGreaterThan(0)
    }
  })

  it('uses purpose codes that satisfy the HCT-102 frozen pattern and have readable labels', () => {
    for (const template of AUTHORIZATION_TEMPLATES) {
      expect(template.purpose).toMatch(PURPOSE_PATTERN)
      expect(purposeLabel(template.purpose)).not.toBe(template.purpose)
    }
    for (const option of PURPOSE_OPTIONS) {
      expect(option.code).toMatch(PURPOSE_PATTERN)
      expect(option.label.length).toBeGreaterThan(0)
      expect(option.description.length).toBeGreaterThan(0)
    }
  })

  it('suggests a bounded validity for every template', () => {
    for (const template of AUTHORIZATION_TEMPLATES) {
      expect(template.suggestedDays).toBeGreaterThanOrEqual(1)
      expect(template.suggestedDays).toBeLessThanOrEqual(90)
    }
  })

  it('keeps the temporary helper template shorter than the daily-care template', () => {
    const daily = AUTHORIZATION_TEMPLATES.find(item => item.id === 'daily-family-care')
    const temporary = AUTHORIZATION_TEMPLATES.find(item => item.id === 'temporary-helper')
    expect(daily).toBeDefined()
    expect(temporary).toBeDefined()
    expect(temporary!.suggestedDays).toBeLessThan(daily!.suggestedDays)
  })
})

describe('applyTemplate', () => {
  it('returns independent copies with the suggested expiry from now', () => {
    const template = AUTHORIZATION_TEMPLATES[0]!
    const now = new Date('2026-08-25T08:00:00Z')
    const draft = applyTemplate(template, now)

    expect(draft.dataFields).toEqual(template.dataFields)
    expect(draft.dataFields).not.toBe(template.dataFields)
    expect(draft.actions).toEqual(template.actions)
    expect(draft.actions).not.toBe(template.actions)
    expect(draft.purpose).toBe(template.purpose)

    const expected = new Date(now)
    expected.setDate(expected.getDate() + template.suggestedDays)
    expect(Math.abs(Date.parse(draft.validUntil) - expected.getTime())).toBeLessThan(60_000)
  })
})

describe('purposeLabel', () => {
  it('maps known codes to family-friendly labels and echoes unknown codes', () => {
    expect(purposeLabel('family-care')).toBe('家庭日常照护')
    expect(purposeLabel('emergency-care')).toBe('紧急照护')
    expect(purposeLabel('custom.purpose-1')).toBe('custom.purpose-1')
  })
})

describe('expiry helpers', () => {
  it('computes remaining days rounded up', () => {
    const now = new Date('2026-08-25T00:00:00Z')
    expect(daysUntilExpiry('2026-08-28T00:00:00Z', now)).toBe(3)
    expect(daysUntilExpiry('2026-08-25T06:00:00Z', now)).toBe(1)
    expect(daysUntilExpiry('2026-08-24T00:00:00Z', now)).toBe(0)
    expect(daysUntilExpiry('not-a-date', now)).toBeNull()
  })

  it('flags active grants expiring within seven days only', () => {
    const now = new Date('2026-08-25T00:00:00Z')
    expect(isExpiringSoon({ ...baseAuthorization, valid_until: '2026-08-28T00:00:00Z' }, now)).toBe(true)
    expect(isExpiringSoon({ ...baseAuthorization, valid_until: '2026-10-01T00:00:00Z' }, now)).toBe(false)
    expect(
      isExpiringSoon(
        { ...baseAuthorization, valid_until: '2026-08-28T00:00:00Z', revoked_at: '2026-08-20T00:00:00Z' },
        now,
      ),
    ).toBe(false)
    expect(isExpiringSoon({ ...baseAuthorization, valid_until: '2026-08-20T00:00:00Z' }, now)).toBe(false)
  })
})

describe('buildHandoffText', () => {
  it('contains the account, purpose code, scope and expiry so the owner can hand it over', () => {
    const text = buildHandoffText({
      granteeActorId: 'child-1',
      memberName: '奶奶',
      fieldLabels: ['已确认健康事件', '风险确认回执'],
      actionLabels: ['查看已确认事件', '确认风险已知晓'],
      purposeCode: 'family-care',
      validUntilText: '2026/09/24 08:00',
    })

    expect(text).toContain('child-1')
    expect(text).toContain('奶奶')
    expect(text).toContain('已确认健康事件、风险确认回执')
    expect(text).toContain('查看已确认事件、确认风险已知晓')
    expect(text).toContain('family-care')
    expect(text).toContain('家庭日常照护')
    expect(text).toContain('2026/09/24 08:00')
    expect(text).toContain('撤回')
  })

  it('keeps unknown purpose codes verbatim without inventing labels', () => {
    const text = buildHandoffText({
      granteeActorId: 'helper-9',
      memberName: '爷爷',
      fieldLabels: ['已确认健康事件'],
      actionLabels: ['查看已确认事件'],
      purposeCode: 'school-project',
      validUntilText: '2026/09/01 00:00',
    })
    expect(text).toContain('school-project')
    expect(text).not.toContain('undefined')
  })
})

describe('audit labels', () => {
  it('translates access-decision reasons into family-friendly Chinese', () => {
    expect(auditReasonLabel('PURPOSE_MISMATCH')).toBe('用途与授权不一致')
    expect(auditReasonLabel('CONSENT_REVOKED')).toBe('授权已被撤回')
    expect(auditReasonLabel('AUTHORIZATION_EXPIRED')).toBe('授权已过期')
    expect(auditReasonLabel('SELF_MEMBER_SCOPE')).toBe('本人查看自己的记录')
    expect(auditReasonLabel('SOME_NEW_REASON')).toBe('SOME_NEW_REASON')
    expect(auditReasonLabel(null)).toBe('')
  })

  it('translates operations, actions and outcomes', () => {
    expect(auditOperationLabel('CREATE')).toBe('新建授权')
    expect(auditOperationLabel('REVOKE')).toBe('撤回授权')
    expect(auditOperationLabel('ACCESS')).toBe('访问数据')
    expect(auditActionLabel('READ_EVENTS')).toBe('查看已确认事件')
    expect(auditOutcomeLabel('ALLOWED')).toBe('已允许')
    expect(auditOutcomeLabel('DENIED')).toBe('已拒绝')
    expect(auditOutcomeLabel('SUCCESS')).toBe('成功')
  })
})
