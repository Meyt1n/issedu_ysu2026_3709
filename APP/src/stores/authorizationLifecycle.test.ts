import { describe, expect, it } from 'vitest'

import { ApiClientError } from '@/api/client'

import {
  isAuthorizationRejection,
  requireAuthorizationReverification,
  resumeAuthorizationBoundary,
  sessionContextKey,
  updateSession,
  useAuthorizationBoundary,
  useSession,
} from './session'

describe('authorization lifecycle', () => {
  it('recognizes explicit denials and hidden resource denials as fail-closed signals', () => {
    expect(isAuthorizationRejection(new ApiClientError('denied', { status: 401, code: 'UNAUTHENTICATED' }))).toBe(true)
    expect(isAuthorizationRejection(new ApiClientError('denied', { status: 403, code: 'CONSENT_REVOKED' }))).toBe(true)
    expect(isAuthorizationRejection(new ApiClientError('hidden', { status: 404, code: 'RESOURCE_NOT_FOUND' }))).toBe(true)
    expect(isAuthorizationRejection(new ApiClientError('network', { status: 0, code: 'DEPENDENCY_UNAVAILABLE' }))).toBe(false)
  })

  it('clears member selection and invalidates the context key after revocation', () => {
    const { session } = useSession()
    updateSession({ dataMode: 'live', actorId: 'test-actor', accessPurpose: 'family-care', currentMemberId: 'member-1' })
    resumeAuthorizationBoundary()
    const before = sessionContextKey(session)

    requireAuthorizationReverification()

    expect(useAuthorizationBoundary().authorizationBoundary.status).toBe('reverification-required')
    expect(session.currentMemberId).toBe('')
    expect(sessionContextKey(session)).not.toBe(before)
    resumeAuthorizationBoundary()
    expect(useAuthorizationBoundary().authorizationBoundary.status).toBe('active')
  })
})
