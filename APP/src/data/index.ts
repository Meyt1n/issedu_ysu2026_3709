import { ApiClient } from '@/api/client'
import { useSession } from '@/stores/session'

import { demoProvider } from './demoProvider'
import { HttpDataProvider } from './httpProvider'
import type { DataProvider } from './types'

let liveProvider: HttpDataProvider | null = null
let liveProviderBaseUrl: string | null = null

/** 根据会话设置返回当前数据提供方：演示数据或家庭服务器。 */
export function activeProvider(): DataProvider {
  const { session } = useSession()
  if (session.dataMode !== 'live') return demoProvider

  if (!liveProvider || liveProviderBaseUrl !== session.serverBaseUrl) {
    liveProviderBaseUrl = session.serverBaseUrl
    liveProvider = new HttpDataProvider(new ApiClient({ baseUrl: session.serverBaseUrl }), () => ({
      actorId: session.actorId,
      accessPurpose: session.accessPurpose,
    }))
  }
  return liveProvider
}
