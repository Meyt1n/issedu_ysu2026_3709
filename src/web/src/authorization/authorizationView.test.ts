import { describe, expect, it } from 'vitest'

import type { Authorization } from '../api/types'
import { buildAuthorizationPreview } from './authorizationView'

const activeAuthorization: Authorization = {
  id: 'authorization-1',
  household_id: 'household-1',
  member_id: 'member-1',
  grantor_actor_id: 'owner',
  grantee_actor_id: 'caregiver',
  data_fields: ['health_events'],
  actions: ['READ_EVENTS'],
  purpose: 'family-care',
  valid_from: '2026-08-08T00:00:00Z',
  valid_until: '2026-08-09T00:00:00Z',
  revoked_at: null,
  version: 1,
  created_at: '2026-08-08T00:00:00Z',
  updated_at: '2026-08-08T00:00:00Z',
}

describe('buildAuthorizationPreview', () => {
  it('returns only active grants for the selected caregiver', () => {
    const preview = buildAuthorizationPreview(
      [activeAuthorization],
      'caregiver',
      new Date('2026-08-08T12:00:00Z'),
    )

    expect(preview).toEqual([
      {
        authorizationId: 'authorization-1',
        memberId: 'member-1',
        fields: ['health_events'],
        actions: ['READ_EVENTS'],
        purpose: 'family-care',
        validUntil: '2026-08-09T00:00:00Z',
      },
    ])
  })

  it('does not expose revoked, expired, or other-caregiver grants', () => {
    const preview = buildAuthorizationPreview(
      [
        activeAuthorization,
        { ...activeAuthorization, id: 'revoked', revoked_at: '2026-08-08T01:00:00Z' },
        { ...activeAuthorization, id: 'expired', valid_until: '2026-08-08T01:00:00Z' },
        { ...activeAuthorization, id: 'other', grantee_actor_id: 'other-caregiver' },
      ],
      'caregiver',
      new Date('2026-08-08T12:00:00Z'),
    )

    expect(preview).toHaveLength(1)
    expect(preview[0]?.authorizationId).toBe('authorization-1')
  })
})
