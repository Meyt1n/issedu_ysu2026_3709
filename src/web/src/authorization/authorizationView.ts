import type { Authorization, AuthorizationAction } from '../api/types'

export interface AuthorizationPreview {
  authorizationId: string
  memberId: string
  fields: string[]
  actions: AuthorizationAction[]
  purpose: string
  validUntil: string
}

export function isAuthorizationActive(
  authorization: Authorization,
  now: Date = new Date(),
): boolean {
  const validFrom = Date.parse(authorization.valid_from)
  const validUntil = Date.parse(authorization.valid_until)
  const timestamp = now.getTime()

  return (
    authorization.revoked_at === null &&
    Number.isFinite(validFrom) &&
    Number.isFinite(validUntil) &&
    timestamp >= validFrom &&
    timestamp < validUntil
  )
}

export function buildAuthorizationPreview(
  authorizations: Authorization[],
  granteeActorId: string,
  now: Date = new Date(),
): AuthorizationPreview[] {
  return authorizations
    .filter(
      authorization =>
        authorization.grantee_actor_id === granteeActorId &&
        isAuthorizationActive(authorization, now),
    )
    .map(authorization => ({
      authorizationId: authorization.id,
      memberId: authorization.member_id,
      fields: [...authorization.data_fields],
      actions: [...authorization.actions],
      purpose: authorization.purpose,
      validUntil: authorization.valid_until,
    }))
}
