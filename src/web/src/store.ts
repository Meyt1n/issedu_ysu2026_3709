import { computed, reactive, readonly } from 'vue'

import { ApiClientError, apiClient } from './api/client'
import { clearChatSessionsForActor } from './assistant/chatSession'
import { SHOW_ADVANCED_LAB } from './ui/featureFlags'
import {
  activePortalEntryMode,
  portalEntryConflict,
  portalEntryConflictNotice,
  type PortalEntryConflict,
} from './ui/portalEntry'
import type {
  AuthSession,
  CapabilityResponse,
  Household,
  Member,
  RequestOptions,
} from './api/types'

export type ViewName =
  | 'member-home'
  | 'member-capture'
  | 'member-plans'
  | 'member-records'
  | 'member-help'
  | 'overview'
  | 'members'
  | 'scan'
  | 'review'
  | 'risks'
  | 'plans'
  | 'graph'
  | 'assistant'
  | 'authorizations'
  | 'bigscreen'
  | 'knowledge'
  | 'modellab'
  | 'face-credentials'
  | 'demo-lab'

export type PortalName = 'member' | 'admin'

export const MEMBER_VIEWS: readonly ViewName[] = [
  'member-home',
  'member-capture',
  'member-plans',
  'member-records',
  'member-help',
]

/** Views reachable from both member and admin portals. */
export const SHARED_VIEWS: readonly ViewName[] = ['assistant']

export type SessionStatus = 'signed-out' | 'loading' | 'ready' | 'empty' | 'error'

export const HEALTH_DATA_REFRESH_EVENT = 'hct:health-data-refresh'
export const FACE_FAMILY_STORAGE_KEY = 'hct:face-family-household'
// localStorage is partitioned by port.  The member front door and the admin
// door intentionally use different ports, so keep the same non-secret device
// binding in a same-host cookie as a cross-port fallback.  The server still
// verifies the household and face credential; this value only selects the
// household whose gallery may be searched.
const FACE_FAMILY_COOKIE_KEY = 'hct-face-family-household'

interface BoundFaceHousehold {
  id: string
  name: string
}

export interface Toast {
  id: number
  kind: 'success' | 'error' | 'info'
  text: string
}

interface SessionState {
  actorId: string
  sessionToken: string
  sessionExpiresAt: number | null
  authMode: 'development' | 'session'
  accessPurpose: string
  status: SessionStatus
  error: string
  currentView: ViewName
  portal: PortalName
  households: Household[]
  selectedHouseholdId: string
  members: Member[]
  selectedMemberId: string
  isOwnerView: boolean
  capabilities: CapabilityResponse | null
  loadingScope: boolean
  pendingReviewCount: number
  toasts: Toast[]
  assistantSeedPrompt: string
  /**
   * HCT-453：登录账号的真实门户与当前入口（成员前台 / 管理后台端口）不匹配。
   * 命中时会话已被登出，欢迎页据此渲染跨端指引按钮。
   */
  entryConflict: PortalEntryConflict | null
}

const state = reactive<SessionState>({
  actorId: '',
  sessionToken: '',
  sessionExpiresAt: null,
  authMode: 'development',
  accessPurpose: 'family-care',
  status: 'signed-out',
  error: '',
  currentView: 'overview',
  portal: 'member',
  households: [],
  selectedHouseholdId: '',
  members: [],
  selectedMemberId: '',
  isOwnerView: false,
  capabilities: null,
  loadingScope: false,
  pendingReviewCount: 0,
  toasts: [],
  assistantSeedPrompt: '',
  entryConflict: null,
})

let toastSeq = 0
let sessionExpiryTimer: ReturnType<typeof setTimeout> | null = null

export const session = readonly(state)

export const requestOptions = computed<RequestOptions>(() => ({
  actorId: state.sessionToken ? undefined : state.actorId.trim() || undefined,
  sessionToken: state.sessionToken || undefined,
  accessPurpose: state.accessPurpose.trim() || undefined,
}))

export const selectedHousehold = computed(
  () => state.households.find(item => item.id === state.selectedHouseholdId) ?? null,
)

export const selectedMember = computed(
  () => state.members.find(item => item.id === state.selectedMemberId) ?? null,
)

export const memberNames = computed(
  () => new Map(state.members.map(member => [member.id, member.display_name])),
)

export function createIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function formatError(cause: unknown): string {
  if (cause instanceof ApiClientError) {
    // 超时 ≠ 服务不可用：服务端（例如人脸注册的本地推理）可能仍在处理并随后
    // 完成保存，不能宣称「没有改变任何数据」（HCT-424 误报根因之一）。
    if (cause.code === 'REQUEST_TIMEOUT') {
      return '本地服务响应超时：请求可能仍在后台处理。请稍候点“刷新”确认结果，再决定是否重试。'
    }
    if (cause.code === 'DEPENDENCY_UNAVAILABLE') {
      return (
        '本地 API 服务不可用，本次没有改变任何数据。无法连接本地 API：'
        + '请确认 API 已在 8000 端口运行（本地进程 scripts/start api，'
        + '或 Docker Compose 的 api 服务处于 healthy），并用 /health 验证后重试。'
      )
    }
    if (cause.message === 'KNOWLEDGE_STEWARD_REQUIRED') {
      return (
        '需要知识管理员身份：请把 Actor 切换为 demo-parent / knowledge-steward'
        + '（或任意 demo- 演示账号），或由负责人把账号加入 .env 的 '
        + 'KNOWLEDGE_ADMIN_ACTORS 后重启 API。'
      )
    }
    if (cause.message === 'KNOWLEDGE_CRAWL_CONFIG_MISSING') {
      return (
        '爬虫配置缺失：API 运行目录里找不到 docs/knowledge/crawl/allowlist.json 与夹具。'
        + 'Compose 部署请重新构建 api 镜像（docker compose build api）后再试。'
      )
    }
    if (cause.message === 'REAL_AUTH_REQUIRED') {
      return '当前部署已关闭开发身份头（ALLOW_DEV_ACTOR_HEADER=false），请改用正式账号登录。'
    }
    if (cause.status === 401) {
      if (cause.message === 'SESSION_REQUIRED' || cause.message === 'AUTH_REQUIRED') {
        return '此操作需要正式账号会话，请切换到“正式账号登录”后重试。'
      }
      return state.authMode === 'session'
        ? '账号、密码或会话无效，请重新登录。'
        : '需要先填写开发身份才能继续这次请求。'
    }
    if (cause.status === 403) {
      if (cause.message === 'CONFIRMATION_FAILED') return '二次确认失败，请检查当前账号的 PIN 或密码后重试。'
      if (cause.message === 'STEP_UP_FAILED') return '二次确认未通过，请重新发起确认后重试。'
      return '当前账号没有执行此操作的权限。'
    }
    if (cause.status === 404) return '当前身份无权访问该资源，或资源不存在。'
    if (cause.status === 409) {
      if (cause.message === 'FACE_CREDENTIAL_EXISTS') {
        return '当前身份已经有有效的人脸凭证；如需替换，请勾选“已有凭证时重新绑定”。'
      }
      if (cause.message === 'ACCOUNT_ID_EXISTS') return '这个登录账号已经在当前家庭使用，请换一个账号 ID。'
      if (cause.message === 'PIN_NOT_CONFIGURED') return '当前家庭账号尚未配置 PIN，请改用账号密码确认。'
      if (cause.message === 'STEP_UP_EXPIRED' || cause.message === 'STEP_UP_REPLAY') {
        return '二次确认已过期或已使用，请重新发起确认。'
      }
      return '数据已在其它位置被修改，请刷新后再试。'
    }
    if (cause.status === 422) {
      if (cause.message === 'FACE_FRAME_LOW_QUALITY') {
        return '摄像头画面太小或过暗过亮：请确认摄像头分辨率不低于 480×360，避免全黑画面或强逆光，然后重新采集。'
      }
      if (cause.message === 'FACE_TOO_SMALL') return '人脸在画面中太小，请靠近摄像头，让整张脸约占画面六分之一以上。'
      if (cause.message === 'FACE_TOO_LARGE') return '人脸在画面中过大或贴边，请稍退后，保证整张脸完整入画。'
      if (cause.message === 'FACE_POSE_EXTREME') return '头部偏转过大，请不要侧脸到接近侧面，按提示轻微转头即可。'
      if (cause.message === 'FACE_BLURRY') return '人脸区域不够清晰，请稳住手机/摄像头并改善光线后重试。'
      if (cause.message === 'FACE_NOT_FOUND') return '图片中没有检测到清晰人脸，请重新拍摄正面照片。'
      if (cause.message === 'FACE_MULTIPLE_SUBJECTS') return '图片中检测到多张人脸，请只保留要绑定的一个人。'
      if (cause.message === 'FACE_LIVENESS_FAILED') return '动态采集没有形成有效转头变化，请正对镜头后按提示缓慢左右转动头部，再重新采集。'
      return `请求内容未通过校验：${cause.message}`
    }
    if (cause.status === 503 && cause.message === 'FACE_DETECTOR_UNAVAILABLE') {
      // 后端已把「本地人脸模型缺失 / ONNX 加载失败（含 Windows 中文路径）」
      // 统一译为该稳定错误码，绝不透出 OpenCV C++ 堆栈或本机完整路径。
      return (
        '人脸功能暂时不可用：本地人脸模型缺失或加载失败，本次没有改变任何数据。'
        + '登录请改用家庭 PIN 或账号密码；管理员可先运行 uv run python scripts/ensure_face_models.py '
        + '预下载模型，再按《人脸凭证录入与登录操作手册》排查后重试。'
      )
    }
    if (cause.status === 503 && cause.message === 'FACE_AUTH_UNAVAILABLE') {
      return '人脸识别暂时不可用，本次未进入家庭；请改用 PIN 或账号密码登录。'
    }
    if (cause.status === 429) {
      const lockMatch = /^LOCKED:(\d+)$/.exec(cause.message)
      if (lockMatch) {
        const waitMinutes = Math.max(1, Math.ceil(Number(lockMatch[1]) / 60))
        return `连续失败次数过多，已临时锁定，请约 ${waitMinutes} 分钟后再试，或改用账号密码登录。`
      }
      return '尝试过于频繁，请稍后再试。'
    }
    if (cause.status >= 500) {
      // 开发部署会返回真实 detail；带上它比统一说“暂时不可用”更可诊断。
      const detail = cause.message && !cause.message.startsWith('API request failed')
        ? `：${cause.message}`
        : ''
      return `本地 API 处理该请求时出错（HTTP ${cause.status}${detail}），本次没有改变任何数据。`
    }
  }
  return '请求未能完成，页面不会显示未经授权的健康数据。'
}

export function pushToast(kind: Toast['kind'], text: string): void {
  const id = ++toastSeq
  state.toasts.push({ id, kind, text })
  setTimeout(() => {
    const index = state.toasts.findIndex(toast => toast.id === id)
    if (index >= 0) state.toasts.splice(index, 1)
  }, 4600)
}

export function dismissToast(id: number): void {
  const index = state.toasts.findIndex(toast => toast.id === id)
  if (index >= 0) state.toasts.splice(index, 1)
}

export function setView(view: ViewName): void {
  if (
    state.portal === 'member' &&
    !MEMBER_VIEWS.includes(view) &&
    !SHARED_VIEWS.includes(view)
  ) {
    state.currentView = 'member-home'
    return
  }
  if (state.portal === 'admin' && MEMBER_VIEWS.includes(view)) {
    state.currentView = 'overview'
    return
  }
  // 研发入口在生产构建默认隐藏（HCT-439 阶段三），直接访问回落到总览。
  if (view === 'modellab' && !SHOW_ADVANCED_LAB) {
    state.currentView = 'overview'
    return
  }
  state.currentView = view
}

export function openAssistantWithPrompt(prompt: string): void {
  state.assistantSeedPrompt = prompt.trim()
  setView('assistant')
}

export function consumeAssistantSeedPrompt(): string {
  const prompt = state.assistantSeedPrompt
  state.assistantSeedPrompt = ''
  return prompt
}

function sessionIsSignedOut(): boolean {
  return state.status === 'signed-out'
}

export function requestHealthDataRefresh(): void {
  globalThis.dispatchEvent?.(new Event(HEALTH_DATA_REFRESH_EVENT))
}

export function onHealthDataRefresh(listener: () => void): () => void {
  const handler = () => listener()
  globalThis.addEventListener?.(HEALTH_DATA_REFRESH_EVENT, handler)
  return () => globalThis.removeEventListener?.(HEALTH_DATA_REFRESH_EVENT, handler)
}

export function setIdentityDraft(actorId: string, accessPurpose: string): void {
  state.actorId = actorId
  state.accessPurpose = accessPurpose
}

export function signOut(): void {
  const token = state.sessionToken
  if (token) void apiClient.logout(token).catch(() => undefined)
  clearSessionContext()
}

function clearSessionContext(): void {
  if (sessionExpiryTimer !== null) {
    clearTimeout(sessionExpiryTimer)
    sessionExpiryTimer = null
  }
  clearChatSessionsForActor(state.actorId)
  state.actorId = ''
  state.sessionToken = ''
  state.sessionExpiresAt = null
  state.status = 'signed-out'
  state.error = ''
  state.entryConflict = null
  state.currentView = 'overview'
  state.portal = 'member'
  state.households = []
  state.selectedHouseholdId = ''
  state.members = []
  state.selectedMemberId = ''
  state.isOwnerView = false
  state.pendingReviewCount = 0
  state.capabilities = null
}

function scheduleSessionExpiry(sessionToken: string, expiresAt: number): void {
  if (sessionExpiryTimer !== null) clearTimeout(sessionExpiryTimer)

  const delayMs = Math.max(0, expiresAt * 1000 - Date.now())
  sessionExpiryTimer = setTimeout(() => {
    sessionExpiryTimer = null
    if (state.sessionToken === sessionToken) expireSession()
  }, delayMs)
}

export function expireSession(): void {
  clearSessionContext()
  state.error = '会话已过期或已被撤销，请重新登录。'
}

/**
 * HCT-453：账号真实门户与当前入口不匹配时，撤销本次登录并留下跨端指引。
 * 入口锁只做减法（不在错误端口渲染另一门户的界面），授权真相仍由服务端
 * 的 HCT-439 owner 判定与成员级授权决定。
 */
function rejectPortalEntry(conflict: PortalEntryConflict): void {
  const notice = portalEntryConflictNotice(conflict)
  signOut()
  state.entryConflict = conflict
  state.error = notice.message
}

export async function connect(actorId: string, accessPurpose: string): Promise<void> {
  clearSessionContext()
  state.actorId = actorId.trim()
  state.accessPurpose = accessPurpose.trim()
  state.authMode = 'development'
  if (!state.actorId) {
    state.status = 'signed-out'
    state.error = '请先填写开发身份。'
    return
  }

  state.status = 'loading'
  state.error = ''
  state.households = []
  state.selectedHouseholdId = ''
  state.members = []
  state.selectedMemberId = ''
  state.isOwnerView = false
  state.portal = 'member'
  try {
    state.households = await apiClient.listHouseholds(requestOptions.value)
    if (state.households.length === 0) {
      state.status = 'empty'
      return
    }
    state.selectedHouseholdId = state.households[0]?.id ?? ''
    await loadHouseholdScope()
    if (sessionIsSignedOut()) return
    state.status = 'ready'
  } catch (cause) {
    state.status = 'error'
    state.error = formatError(cause)
  }
}

function parseBoundFaceHousehold(raw: string): BoundFaceHousehold | null {
  const value = raw.trim()
  if (!value) return null
  try {
    if (value.startsWith('{')) {
      const parsed = JSON.parse(value) as Partial<BoundFaceHousehold>
      if (typeof parsed.id === 'string' && parsed.id.trim()) {
        return { id: parsed.id.trim(), name: typeof parsed.name === 'string' ? parsed.name.trim() : '' }
      }
    }
    // Keep old plain household ids readable after upgrading the web client.
    return { id: value, name: '' }
  } catch {
    return null
  }
}

function readFaceBindingCookie(): BoundFaceHousehold | null {
  try {
    const cookie = globalThis.document?.cookie ?? ''
    const pair = cookie
      .split(';')
      .map(item => item.trim())
      .find(item => item.startsWith(`${FACE_FAMILY_COOKIE_KEY}=`))
    if (!pair) return null
    const encoded = pair.slice(FACE_FAMILY_COOKIE_KEY.length + 1)
    return parseBoundFaceHousehold(decodeURIComponent(encoded))
  } catch {
    return null
  }
}

function writeFaceBindingCookie(value: string): void {
  try {
    if (globalThis.document) {
      globalThis.document.cookie = `${FACE_FAMILY_COOKIE_KEY}=${encodeURIComponent(value)}; Path=/; SameSite=Lax`
    }
  } catch {
    // A single-origin deployment can continue to use localStorage.
  }
}

function readBoundFaceHousehold(): BoundFaceHousehold | null {
  try {
    const raw = globalThis.localStorage?.getItem(FACE_FAMILY_STORAGE_KEY)?.trim() ?? ''
    const local = parseBoundFaceHousehold(raw)
    if (local) {
      // Upgrade an existing 5174/5184-only binding without asking the family
      // to register again.  Reloading the bound portal mirrors it to the
      // same-host cookie, which the 5173/5183 member portal can then read.
      writeFaceBindingCookie(JSON.stringify(local))
      return local
    }
  } catch {
    // Fall through to the same-host cookie when storage is unavailable.
  }
  return readFaceBindingCookie()
}

export function getBoundFaceHouseholdId(): string {
  return readBoundFaceHousehold()?.id ?? ''
}

export function getBoundFaceHouseholdName(): string {
  return readBoundFaceHousehold()?.name ?? ''
}

export function bindFaceHousehold(householdId: string, householdName = ''): void {
  const id = householdId.trim()
  if (!id) return
  const previous = readBoundFaceHousehold()
  const value = JSON.stringify({
    id,
    name: householdName.trim() || (previous?.id === id ? previous.name : ''),
  })
  try {
    globalThis.localStorage?.setItem(FACE_FAMILY_STORAGE_KEY, value)
  } catch {
    // Private browsing may disable storage; the same-host cookie remains available.
  }
  writeFaceBindingCookie(value)
}

export function clearBoundFaceHousehold(): void {
  try {
    globalThis.localStorage?.removeItem(FACE_FAMILY_STORAGE_KEY)
  } catch {
    // Ignore storage cleanup failures; no authentication state is persisted here.
  }
  try {
    if (globalThis.document) {
      globalThis.document.cookie = `${FACE_FAMILY_COOKIE_KEY}=; Max-Age=0; Path=/; SameSite=Lax`
    }
  } catch {
    // Ignore cookie cleanup failures for the same reason as localStorage above.
  }
}

/**
 * 登录前预取本地能力声明（`/meta/capabilities` 是公开元数据接口，不需要
 * 鉴权）。欢迎页据此判断人脸识别模型是否就绪；此前该状态只在登录后的
 * `loadHouseholdScope` 里加载，冷加载的欢迎页会把已绑定设备误判为
 * “人脸登录暂时不可用”。失败时保留已有值，由页面引导改用 PIN/密码。
 */
export async function refreshCapabilities(): Promise<void> {
  try {
    state.capabilities = await apiClient.getCapabilities()
  } catch {
    // 探测失败不清空已有能力声明，也不阻塞欢迎页；人脸不可用时页面自带回退。
  }
}

async function enterAuthenticatedSession(
  sessionResult: AuthSession,
  preferredHouseholdId = '',
): Promise<void> {
  state.sessionToken = sessionResult.session_token
  state.sessionExpiresAt = sessionResult.expires_at
  scheduleSessionExpiry(state.sessionToken, state.sessionExpiresAt)
  state.actorId = sessionResult.actor_id
  state.households = await apiClient.listHouseholds(requestOptions.value)
  if (state.households.length === 0) {
    state.status = 'empty'
    return
  }

  const requestedHouseholdId = sessionResult.household_id || preferredHouseholdId
  state.selectedHouseholdId =
    requestedHouseholdId && state.households.some(item => item.id === requestedHouseholdId)
      ? requestedHouseholdId
      : state.households[0]?.id ?? ''
  await loadHouseholdScope()
  if (sessionIsSignedOut()) return
  state.status = 'ready'
}

export async function connectWithPassword(
  actorId: string,
  password: string,
  accessPurpose: string,
  register = false,
): Promise<void> {
  clearSessionContext()
  state.authMode = 'session'
  state.actorId = actorId.trim()
  state.accessPurpose = accessPurpose.trim()
  if (!state.actorId || !password) {
    state.status = 'signed-out'
    state.error = '请输入本地账号和密码。'
    return
  }

  state.status = 'loading'
  state.error = ''
  try {
    if (register) await apiClient.registerAccount(state.actorId, password)
    await enterAuthenticatedSession(await apiClient.login(state.actorId, password))
  } catch (cause) {
    const sessionExpired = sessionIsSignedOut() && state.error.includes('会话已过期')
    if (!sessionExpired) clearSessionContext()
    state.authMode = 'session'
    state.status = 'signed-out'
    if (sessionExpired) return
    state.error = formatError(cause)
  }
}

export async function connectWithPin(
  actorId: string,
  householdId: string,
  pin: string,
  accessPurpose: string,
): Promise<void> {
  clearSessionContext()
  state.authMode = 'session'
  state.actorId = actorId.trim()
  state.accessPurpose = accessPurpose.trim()
  if (!state.actorId || !householdId.trim() || !/^\d{6}$/.test(pin)) {
    state.status = 'signed-out'
    state.error = '请输入家庭、身份和六位数字 PIN。'
    return
  }

  state.status = 'loading'
  state.error = ''
  try {
    await enterAuthenticatedSession(
      await apiClient.loginWithPin(householdId.trim(), state.actorId, pin),
      householdId.trim(),
    )
  } catch (cause) {
    const sessionExpired = sessionIsSignedOut() && state.error.includes('会话已过期')
    if (!sessionExpired) clearSessionContext()
    state.authMode = 'session'
    state.status = 'signed-out'
    if (sessionExpired) return
    state.error = formatError(cause)
  }
}

export async function connectWithFace(
  actorId: string,
  householdId: string,
  frames: File[],
  accessPurpose: string,
): Promise<void> {
  clearSessionContext()
  state.authMode = 'session'
  state.actorId = actorId.trim()
  state.accessPurpose = accessPurpose.trim()
  if (!state.actorId || !householdId.trim() || frames.length < 2) {
    state.status = 'signed-out'
    state.error = '需要选择家庭、账号并完成摄像头活体采集。'
    return
  }

  state.status = 'loading'
  state.error = ''
  try {
    const challenge = await apiClient.createFaceChallenge(householdId.trim(), state.actorId)
    await enterAuthenticatedSession(
      await apiClient.loginWithFace(
        householdId.trim(),
        state.actorId,
        challenge.challenge_id,
        frames,
      ),
      householdId.trim(),
    )
  } catch (cause) {
    const sessionExpired = sessionIsSignedOut() && state.error.includes('会话已过期')
    if (!sessionExpired) clearSessionContext()
    state.authMode = 'session'
    state.status = 'signed-out'
    if (sessionExpired) return
    state.error = cause instanceof ApiClientError && cause.status === 401
      ? '人脸验证未通过。请确认这个家庭账号已经绑定人脸，并保持正面、光线均匀；也可以改用 PIN 或密码登录。'
      : formatError(cause)
  }
}

export async function connectWithFamilyFace(
  householdId: string,
  frames: File[],
  accessPurpose: string,
): Promise<void> {
  clearSessionContext()
  state.authMode = 'session'
  state.accessPurpose = accessPurpose.trim()
  if (!householdId.trim() || frames.length < 2) {
    state.status = 'signed-out'
    state.error = '需要先绑定家庭，并完成摄像头动态采集。'
    return
  }

  state.status = 'loading'
  state.error = ''
  try {
    const household = householdId.trim()
    const challenge = await apiClient.createFamilyFaceChallenge(household)
    const sessionResult = await apiClient.loginWithFamilyFace(
      household,
      challenge.challenge_id,
      frames,
    )
    await enterAuthenticatedSession(sessionResult, household)
    const matchedHousehold = state.households.find(item => item.id === state.selectedHouseholdId)
    bindFaceHousehold(household, matchedHousehold?.name ?? '')
  } catch (cause) {
    const sessionExpired = sessionIsSignedOut() && state.error.includes('会话已过期')
    if (!sessionExpired) clearSessionContext()
    state.authMode = 'session'
    state.status = 'signed-out'
    if (sessionExpired) return
    state.error = cause instanceof ApiClientError && cause.status === 401
      ? '没有在这个家庭中找到明确的人脸匹配。请重新采集，或改用 PIN/账号登录。'
      : formatError(cause)
  }
}

export async function createHouseholdAndEnter(
  householdName: string,
  memberDrafts: Array<{ displayName: string; role: 'SELF' | 'DEPENDENT' | 'CAREGIVER'; actorId?: string }>,
): Promise<void> {
  const created = await apiClient.createHousehold(
    { name: householdName },
    { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
  )
  for (const draft of memberDrafts) {
    if (!draft.displayName.trim()) continue
    await apiClient.createMember(
      created.id,
      {
        display_name: draft.displayName.trim(),
        role: draft.role,
        actor_id: draft.actorId?.trim() || undefined,
      },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
  }
  state.households = await apiClient.listHouseholds(requestOptions.value)
  state.selectedHouseholdId = created.id
  await loadHouseholdScope()
  if (sessionIsSignedOut()) return
  state.status = 'ready'
}

export async function selectHousehold(householdId: string): Promise<void> {
  if (state.selectedHouseholdId === householdId) return
  state.selectedHouseholdId = householdId
  await loadHouseholdScope()
}

export function selectMember(memberId: string): void {
  state.selectedMemberId = memberId
}

export function portalWelcomeMessage(): string {
  if (state.portal === 'member') {
    const name = state.members.find(member => member.id === state.selectedMemberId)?.display_name
    return name ? `你好，${name}。欢迎回家。` : '欢迎回家。'
  }
  return '已进入家庭管理后台。'
}

export async function loadHouseholdScope(): Promise<void> {
  const householdId = state.selectedHouseholdId
  if (!householdId) return

  state.loadingScope = true
  state.error = ''
  state.members = []
  state.selectedMemberId = ''
  state.isOwnerView = false
  try {
    state.members = await apiClient.listMembers(householdId, requestOptions.value)
    // A family-face session already tells us which small account was matched.
    // Keep that member selected when the scope loads instead of silently
    // falling back to the first member in the household.
    state.selectedMemberId =
      state.members.find(member => member.actor_id === state.actorId)?.id ??
      state.members[0]?.id ??
      ''

    // The household owner is explicit in the household scope.  Do not probe
    // the owner-only authorization endpoint to infer a portal: a member login
    // should never need to touch an admin route.
    state.isOwnerView =
      state.households.find(item => item.id === householdId)?.created_by === state.actorId

    state.portal = state.isOwnerView ? 'admin' : 'member'

    // HCT-453：入口锁。成员前台端口不渲染管理后台、管理后台端口不渲染
    // 成员前台；不匹配时登出并让欢迎页给出「去另一入口」指引。
    const conflict = portalEntryConflict(activePortalEntryMode(), state.portal)
    if (conflict) {
      rejectPortalEntry(conflict)
      return
    }

    const allowedViews = state.portal === 'admin' ? undefined : MEMBER_VIEWS
    if (allowedViews && !allowedViews.includes(state.currentView)) {
      state.currentView = 'member-home'
    } else if (!allowedViews && MEMBER_VIEWS.includes(state.currentView)) {
      state.currentView = 'overview'
    }

    try {
      state.capabilities = await apiClient.getCapabilities(requestOptions.value)
    } catch {
      state.capabilities = null
    }

    if (state.portal === 'admin') {
      await refreshPendingReviewCount()
    } else {
      state.pendingReviewCount = 0
    }
  } catch (cause) {
    state.members = []
    if (!sessionIsSignedOut()) state.error = formatError(cause)
  } finally {
    state.loadingScope = false
  }
}

export async function refreshMembers(): Promise<void> {
  const householdId = state.selectedHouseholdId
  if (!householdId) return
  state.members = await apiClient.listMembers(householdId, requestOptions.value)
  if (!state.members.some(member => member.id === state.selectedMemberId)) {
    state.selectedMemberId = state.members[0]?.id ?? ''
  }
  if (state.portal === 'admin') await refreshPendingReviewCount()
}

export async function refreshPendingReviewCount(): Promise<void> {
  const householdId = state.selectedHouseholdId
  if (!householdId || state.portal !== 'admin' || state.members.length === 0) {
    state.pendingReviewCount = 0
    return
  }
  const results = await Promise.allSettled(
    state.members.map(member =>
      apiClient.listReviewTasks(householdId, member.id, requestOptions.value),
    ),
  )
  state.pendingReviewCount = results.reduce((total, result) => {
    if (result.status !== 'fulfilled') return total
    return total + result.value.filter(task => task.status === 'PENDING_REVIEW').length
  }, 0)
}

const VISION_TASK_STORAGE = 'hct-vision-tasks'

export function rememberVisionTask(taskId: string): void {
  const key = `${VISION_TASK_STORAGE}:${state.actorId}`
  try {
    const existing = JSON.parse(globalThis.localStorage?.getItem(key) ?? '[]') as string[]
    if (!existing.includes(taskId)) existing.unshift(taskId)
    globalThis.localStorage?.setItem(key, JSON.stringify(existing.slice(0, 30)))
  } catch {
    // localStorage unavailable: task tracking degrades to the current page session.
  }
}

export function rememberedVisionTasks(): string[] {
  const key = `${VISION_TASK_STORAGE}:${state.actorId}`
  try {
    return JSON.parse(globalThis.localStorage?.getItem(key) ?? '[]') as string[]
  } catch {
    return []
  }
}

apiClient.setUnauthorizedHandler(() => {
  if (state.sessionToken) expireSession()
})

