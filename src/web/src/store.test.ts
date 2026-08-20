import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './api/client'
import { connectWithPassword, session, signOut } from './store'

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
