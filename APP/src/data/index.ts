import { ApiClient, ApiClientError } from '@/api/client'
import {
  isAuthorizationRejection,
  requireAuthorizationReverification,
  sessionContextKey,
  useAuthorizationBoundary,
  useSession,
} from '@/stores/session'
import { clearCapabilities } from '@/stores/capabilities'

import { demoProvider } from './demoProvider'
import { HttpDataProvider } from './httpProvider'
import type { DataProvider } from './types'

let liveProvider: HttpDataProvider | null = null
let liveProviderKey: string | null = null

function authorizationBlockedProvider(): DataProvider {
  return new Proxy({} as DataProvider, {
    get(_target, property) {
      if (typeof property !== 'string') return undefined
      return () => Promise.reject(new ApiClientError('授权状态需要重新验证', {
        status: 403,
        code: 'AUTHORIZATION_REVERIFICATION_REQUIRED',
      }))
    },
  })
}

/**
 * A single authorization denial invalidates every page's context key. No API
 * response is cached locally: capabilities, selected member and provider
 * in-memory state are discarded before callers render their error guidance.
 */
function guardAuthorization(provider: DataProvider): DataProvider {
  return new Proxy(provider, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver)
      if (typeof value !== 'function') return value
      return (...args: unknown[]) => Promise.resolve(value.apply(target, args)).catch((cause: unknown) => {
        if (isAuthorizationRejection(cause)) {
          clearCapabilities()
          requireAuthorizationReverification()
          liveProvider = null
          liveProviderKey = null
        }
        throw cause
      })
    },
  }) as DataProvider
}

/** Returns the active provider with a fail-closed authorization boundary in live mode. */
export function activeProvider(): DataProvider {
  const { session } = useSession()
  const { authorizationBoundary } = useAuthorizationBoundary()
  if (session.dataMode !== 'live') return demoProvider
  if (authorizationBoundary.status !== 'active') return authorizationBlockedProvider()

  const providerKey = sessionContextKey(session)
  if (!liveProvider || liveProviderKey !== providerKey) {
    liveProviderKey = providerKey
    liveProvider = new HttpDataProvider(new ApiClient({ baseUrl: session.serverBaseUrl }), () => ({
      actorId: session.actorId,
      accessPurpose: session.accessPurpose,
    }))
  }
  return guardAuthorization(liveProvider)
}
