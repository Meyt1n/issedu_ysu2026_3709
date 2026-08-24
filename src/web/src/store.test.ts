import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './api/client'
import {
  connectWithFamilyFace,
  connectWithPassword,
  selectedMember,
  session,
  signOut,
} from './store'

describe('session expiry handling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(apiClient, 'login').mockResolvedValue({
      actor_id: 'expiry-owner',
      session_token: 'e'.repeat(48),
      expires_at: (Date.now() + 5000) / 1000,
    })
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([])
  })

  afterEach(() => {
    signOut()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('clears the session when the server expiry timestamp is reached', async () => {
    await connectWithPassword('expiry-owner', 'password-123', 'family-care')
    expect(session.sessionToken).toHaveLength(48)
    expect(session.sessionExpiresAt).not.toBeNull()

    vi.advanceTimersByTime(5000)

    expect(session.sessionToken).toBe('')
    expect(session.status).toBe('signed-out')
    expect(session.error).toContain('会话已过期')
  })

  it('cancels the expiry timer when the user signs out early', async () => {
    await connectWithPassword('expiry-owner', 'password-123', 'family-care')
    signOut()
    vi.advanceTimersByTime(5000)

    expect(session.error).toBe('')
    expect(session.status).toBe('signed-out')
  })
})

describe('family face entry context', () => {
  afterEach(() => {
    signOut()
    vi.restoreAllMocks()
  })

  it('selects the member returned by family face identification', async () => {
    vi.spyOn(apiClient, 'createFamilyFaceChallenge').mockResolvedValue({
      challenge_id: 'c'.repeat(24),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    vi.spyOn(apiClient, 'loginWithFamilyFace').mockResolvedValue({
      actor_id: 'grandma-local',
      household_id: 'household-family',
      session_token: 's'.repeat(48),
      expires_at: (Date.now() + 60_000) / 1000,
    })
    vi.spyOn(apiClient, 'listHouseholds').mockResolvedValue([
      {
        id: 'household-family',
        name: '爷爷奶奶家',
        created_by: 'parent-local',
        created_at: '2026-08-22T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listMembers').mockResolvedValue([
      {
        id: 'grandpa-member',
        household_id: 'household-family',
        display_name: '爷爷',
        role: 'DEPENDENT',
        actor_id: 'grandpa-local',
        created_at: '2026-08-22T00:00:00Z',
      },
      {
        id: 'grandma-member',
        household_id: 'household-family',
        display_name: '奶奶',
        role: 'DEPENDENT',
        actor_id: 'grandma-local',
        created_at: '2026-08-22T00:00:00Z',
      },
    ])
    vi.spyOn(apiClient, 'listAuthorizations').mockResolvedValue([])
    vi.spyOn(apiClient, 'getCapabilities').mockResolvedValue({
      phase: 'P0',
      available: [],
      unavailable: [],
    })

    await connectWithFamilyFace(
      'household-family',
      [new File(['frame-1'], 'frame-1.jpg'), new File(['frame-2'], 'frame-2.jpg')],
      'family-care',
    )

    expect(session.status).toBe('ready')
    expect(session.actorId).toBe('grandma-local')
    expect(session.selectedHouseholdId).toBe('household-family')
    expect(session.selectedMemberId).toBe('grandma-member')
    expect(selectedMember.value?.display_name).toBe('奶奶')
    expect(session.portal).toBe('member')
    expect(session.currentView).toBe('member-home')
  })
})
