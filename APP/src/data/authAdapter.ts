import { createHttpAuthAdapter } from '@/api/auth'
import type { AuthAdapter } from '@/api/auth'
import { authSessionSlot } from '@/stores/auth'
import { useSession } from '@/stores/session'

/**
 * 家庭服务器正式鉴权适配器。
 *
 * 按“服务器地址 + 访问目的”缓存实例：地址或目的变化必须换适配器，
 * 避免把上一台家庭服务器的会话带到新地址。会话凭据由 stores/auth 的内存槽位
 * 持有，适配器本身不保存副本，也不写任何存储，因此实例可以长期复用。
 */

let adapter: AuthAdapter | null = null
let adapterKey: string | null = null

/**
 * 取得当前联机配置对应的适配器。
 * 服务器地址不合法时抛出 `AuthAdapterError`（`AUTH_UNAVAILABLE`）。
 */
export function familyAuthAdapter(): AuthAdapter {
  const { session } = useSession()
  const key = [session.serverBaseUrl, session.accessPurpose].join(' | ')
  if (!adapter || adapterKey !== key) {
    adapter = createHttpAuthAdapter({
      baseUrl: session.serverBaseUrl,
      accessPurpose: session.accessPurpose,
      session: authSessionSlot,
    })
    adapterKey = key
  }
  return adapter
}

/** 已创建的适配器；地址未配置过时为 null（登出时不必强行新建）。 */
export function currentAuthAdapter(): AuthAdapter | null {
  return adapter
}
