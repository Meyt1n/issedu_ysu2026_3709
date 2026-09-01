export type WelcomeCredentialMode = 'password' | 'pin' | 'face'

export interface FaceBindingSummary {
  /** 只有人脸 tab 需要本机家庭绑定卡片；PIN/密码不依赖该卡片。 */
  visible: boolean
  bound: boolean
  title: string
  detail: string
  /** 未绑定时的唯一回退动作文案；已绑定或不可见时为空字符串。 */
  fallbackLabel: string
}

export interface MemberUnboundGate {
  blocked: boolean
  title: string
  message: string
  ctaLabel: string
}

const HIDDEN: FaceBindingSummary = {
  visible: false,
  bound: false,
  title: '',
  detail: '',
  fallbackLabel: '',
}

const OPEN_GATE: MemberUnboundGate = {
  blocked: false,
  title: '',
  message: '',
  ctaLabel: '',
}

const BLOCKED_GATE: MemberUnboundGate = {
  blocked: true,
  title: '请先到管理后台',
  message:
    '成员前台只在管理后台保持登录时开放。请先去管理后台登录家庭管理员账号；登录期间这台电脑才可以使用刷脸或 PIN。后台退出或会话结束后，这里会自动收回。',
  ctaLabel: '去管理后台登录',
}

export const ADMIN_READY_COOKIE_KEY = 'hct-admin-ready'

export interface AdminReadyPresence {
  instanceId: string
  householdId: string
}

export interface MemberGatePresence {
  /** Live API process id from `/meta/capabilities`. Empty in older mocks. */
  instanceId?: string
  readyInstanceId?: string
  readyHouseholdId?: string
  /** True until `/meta/capabilities` has returned (or failed) on this page. */
  capabilitiesPending?: boolean
}

export function writeAdminReadyCookie(
  instanceId: string,
  householdId: string,
  maxAgeSeconds = 86400,
): void {
  const instance = instanceId.trim()
  const household = householdId.trim()
  if (!instance || !household || typeof document === 'undefined') return
  const value = encodeURIComponent(JSON.stringify({ instanceId: instance, householdId: household }))
  const maxAge = Math.max(60, Math.floor(maxAgeSeconds))
  document.cookie = `${ADMIN_READY_COOKIE_KEY}=${value}; Path=/; SameSite=Lax; Max-Age=${maxAge}`
}

export function readAdminReadyCookie(): AdminReadyPresence | null {
  if (typeof document === 'undefined') return null
  const pair = document.cookie
    .split(';')
    .map(item => item.trim())
    .find(item => item.startsWith(`${ADMIN_READY_COOKIE_KEY}=`))
  if (!pair) return null
  try {
    const parsed = JSON.parse(decodeURIComponent(pair.slice(ADMIN_READY_COOKIE_KEY.length + 1))) as Partial<AdminReadyPresence>
    if (typeof parsed.instanceId === 'string' && typeof parsed.householdId === 'string') {
      return { instanceId: parsed.instanceId, householdId: parsed.householdId }
    }
  } catch {
    return null
  }
  return null
}

export function clearAdminReadyCookie(): void {
  if (typeof document === 'undefined') return
  document.cookie = `${ADMIN_READY_COOKIE_KEY}=; Max-Age=0; Path=/; SameSite=Lax`
}

/**
 * 成员前台只在管理后台当前保持登录时开放刷脸 / PIN。
 * 本机残留的家庭绑定不够；必须有与当前家庭匹配的管理员就绪 cookie。
 * `instance_id` 用于识别「关掉项目再启动」后的过期就绪标记。
 */
export function memberUnboundGate(
  entryMode: 'member' | 'admin' | 'auto',
  boundHouseholdId: string,
  presence: MemberGatePresence = {},
): MemberUnboundGate {
  if (entryMode !== 'member') return OPEN_GATE
  if (presence.capabilitiesPending) return BLOCKED_GATE
  const bound = boundHouseholdId.trim()
  if (!bound) return BLOCKED_GATE
  const readyHousehold = presence.readyHouseholdId?.trim() ?? ''
  if (readyHousehold !== bound) return BLOCKED_GATE
  const instanceId = presence.instanceId?.trim() ?? ''
  const readyInstance = presence.readyInstanceId?.trim() ?? ''
  if (instanceId && readyInstance !== instanceId) return BLOCKED_GATE
  return OPEN_GATE
}

/** 单入口欢迎页只有在管理后台当前就绪时，才用本机残留绑定开刷脸。 */
export function autoEntryMayUseBoundFace(
  boundHouseholdId: string,
  presence: MemberGatePresence = {},
): boolean {
  return !memberUnboundGate('member', boundHouseholdId, presence).blocked
}

/**
 * 欢迎页本机人脸登录家庭卡片（HCT-425 / HCT-511）。
 *
 * 家庭人脸 1:N 只在本机绑定的家庭内匹配。绑定在管理后台登录时自动完成。
 * PIN 选人使用同一份本机绑定，但不显示这张刷脸卡片。
 */
export function faceBindingSummary(
  credentialMode: WelcomeCredentialMode,
  boundHouseholdId: string,
  boundHouseholdName = '',
): FaceBindingSummary {
  if (credentialMode !== 'face') return HIDDEN
  if (!boundHouseholdId.trim()) {
    return {
      visible: true,
      bound: false,
      title: '本机尚未绑定家庭',
      detail: '请先到管理后台登录一次，这台电脑会自动绑定。',
      fallbackLabel: '',
    }
  }
  return {
    visible: true,
    bound: true,
    title: boundHouseholdName.trim() || '已绑定本机家庭',
    detail: '',
    fallbackLabel: '',
  }
}
