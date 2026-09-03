/**
 * HCT-453 前后台分端口登录入口。
 *
 * 一套 Vue 代码、一个本地 API，通过「入口模式」把同一应用拆成两个登录面：
 *
 * - 成员前台：本地开发 `http://127.0.0.1:5173`，Compose `http://localhost:8080`；
 * - 管理后台：本地开发 `http://127.0.0.1:5174`，Compose `http://localhost:8081`。
 *
 * 入口模式只是 UX 锁：登录后由 HCT-439 的服务端事实（`Household.created_by`）
 * 计算真实门户，入口与门户不匹配时前端拒绝落在错误的界面并给出跨端指引。
 * 它不放大任何权限——后端授权判断完全不读取入口模式。
 *
 * 解析优先级（高到低）：
 * 1. `?portal=member|admin` 查询参数（教学/测试用的显式覆盖）；
 * 2. `VITE_PORTAL_MODE` 构建/开发期 define（`npm run dev:web:member|admin`）；
 * 3. `window.__HCT_PORTAL_MODE__`（Compose Nginx 按监听端口注入）；
 * 4. 已知管理后台端口回退（5174 / 8081 / 5184 → admin）；
 * 5. 都没有 → `auto`：保持 HCT-439 的单入口行为（按账号角色进门户），
 *    供裸 `npm run dev:web` 调试和既有 e2e 使用，不是产品入口。
 */

export type PortalEntryMode = 'member' | 'admin' | 'auto'

/** 已知的管理后台端口：Vite dev 5174、Compose 8081。 */
const ADMIN_ENTRY_PORTS = new Set(['5174', '8081', '5184'])

/** 每个入口的默认公开地址，用于跨端链接的兜底换算。 */
const DEFAULT_DEV_PORTS: Record<'member' | 'admin', string> = {
  member: '5173',
  admin: '5174',
}
const DEFAULT_COMPOSE_PORTS: Record<'member' | 'admin', string> = {
  member: '8080',
  admin: '8081',
}
// 本地多人联调常用的第二组端口：成员前台 5183、管理后台 5184。
// 端口只是入口识别和跨端导航的兜底，授权仍由服务端决定。
const DEFAULT_LOCAL_DEMO_PORTS: Record<'member' | 'admin', string> = {
  member: '5183',
  admin: '5184',
}

function normalizeMode(value: unknown): 'member' | 'admin' | null {
  if (value === 'member' || value === 'admin') return value
  return null
}

export interface PortalEntrySignals {
  /** `?portal=` 查询参数原始值。 */
  queryPortal?: string | null
  /** `import.meta.env.VITE_PORTAL_MODE`。 */
  defineMode?: string | null
  /** `window.__HCT_PORTAL_MODE__`（Nginx sub_filter 注入）。 */
  injectedMode?: unknown
  /** `location.port`。 */
  port?: string | null
}

export function resolvePortalEntryMode(signals: PortalEntrySignals): PortalEntryMode {
  const fromQuery = normalizeMode(signals.queryPortal?.trim())
  if (fromQuery) return fromQuery
  const fromDefine = normalizeMode(signals.defineMode?.trim())
  if (fromDefine) return fromDefine
  const fromInjection = normalizeMode(signals.injectedMode)
  if (fromInjection) return fromInjection
  if (signals.port && ADMIN_ENTRY_PORTS.has(signals.port)) return 'admin'
  return 'auto'
}

function readEnvironmentSignals(): PortalEntrySignals {
  const location = globalThis.location
  let queryPortal: string | null = null
  try {
    queryPortal = location?.search ? new URLSearchParams(location.search).get('portal') : null
  } catch {
    queryPortal = null
  }
  return {
    queryPortal,
    defineMode: import.meta.env.VITE_PORTAL_MODE ?? null,
    injectedMode: (globalThis as Record<string, unknown>).__HCT_PORTAL_MODE__,
    port: location?.port ?? null,
  }
}

let activeEntryMode: PortalEntryMode | null = null

const WELCOME_ENTRY_HINT_KEY = 'hct-welcome-entry-hint'
let memoryWelcomeHint: 'member' | 'admin' | null = null

/** 成员前台退出后，同一标签页的单入口欢迎页仍按成员前台渲染。 */
export function rememberWelcomeEntry(portal: 'member' | 'admin'): void {
  memoryWelcomeHint = portal
  try {
    globalThis.sessionStorage?.setItem(WELCOME_ENTRY_HINT_KEY, portal)
  } catch {
    // Private browsing may disable sessionStorage; in-memory hint still covers this tab.
  }
}

export function readWelcomeEntryHint(): 'member' | 'admin' | null {
  try {
    const value = globalThis.sessionStorage?.getItem(WELCOME_ENTRY_HINT_KEY)
    if (value === 'member' || value === 'admin') return value
  } catch {
    // Fall through to the in-memory hint.
  }
  return memoryWelcomeHint
}

/** 仅供单元测试清理。 */
export function resetWelcomeEntryHintForTest(): void {
  memoryWelcomeHint = null
  try {
    globalThis.sessionStorage?.removeItem(WELCOME_ENTRY_HINT_KEY)
  } catch {
    // Ignore missing Storage in node test environments.
  }
}

/** 当前页面的入口模式；首次调用时从环境解析并缓存。 */
export function activePortalEntryMode(): PortalEntryMode {
  if (activeEntryMode === null) activeEntryMode = resolvePortalEntryMode(readEnvironmentSignals())
  return activeEntryMode
}

/**
 * 欢迎页实际使用的入口。显式 `?portal=` / 端口 / 构建模式优先；
 * 单入口（auto）在本标签刚从成员前台退出时，仍走成员前台品牌和门禁，
 * 避免落回带残留家庭名的刷脸调试页。
 */
export function resolveWelcomeEntryMode(): PortalEntryMode {
  const resolved = activePortalEntryMode()
  if (resolved !== 'auto') return resolved
  return readWelcomeEntryHint() ?? 'auto'
}

/** 仅供单元测试注入入口模式；传 null 恢复按环境解析。 */
export function overridePortalEntryModeForTest(mode: PortalEntryMode | null): void {
  activeEntryMode = mode
}

/**
 * 登录后入口/门户匹配判定。`portal` 是 HCT-439 按服务端事实计算的真实门户。
 * 返回 null 表示允许进入；否则给出需要改用的入口。
 */
export type PortalEntryConflict = 'need-admin-entry' | 'need-member-entry'

export function portalEntryConflict(
  entryMode: PortalEntryMode,
  portal: 'member' | 'admin',
): PortalEntryConflict | null {
  if (entryMode === 'auto') return null
  if (entryMode === portal) return null
  return portal === 'admin' ? 'need-admin-entry' : 'need-member-entry'
}

/**
 * 计算另一入口的公开地址。
 *
 * 优先使用部署方显式配置的公开地址（`VITE_MEMBER_PORTAL_URL` /
 * `VITE_ADMIN_PORTAL_URL`）；否则按当前地址换算端口：开发端口互换
 * 5173↔5174、5183↔5184，Compose 端口互换 8080↔8081；无法判断时返回空字符串，
 * 由界面只显示文字指引而不渲染链接。
 *
 * 换算出的地址总是带上 `?portal=member|admin` 显式覆盖：即使目标端口
 * 的服务没有注入入口模式（配置不全的部署），落地页也按目标入口品牌
 * 渲染，不会又露出另一端的登录面。
 */
export function crossPortalUrl(
  target: 'member' | 'admin',
  currentLocation?: { protocol: string; hostname: string; port: string } | null,
  env: { memberUrl?: string | null; adminUrl?: string | null } = {
    memberUrl: import.meta.env.VITE_MEMBER_PORTAL_URL ?? null,
    adminUrl: import.meta.env.VITE_ADMIN_PORTAL_URL ?? null,
  },
): string {
  const configured = target === 'member' ? env.memberUrl : env.adminUrl
  if (configured && configured.trim()) return withPortalQuery(configured.trim(), target)

  const location = currentLocation ?? globalThis.location ?? null
  if (!location?.hostname) return ''
  const port = location.port
  let targetPort = ''
  if (port === DEFAULT_DEV_PORTS.member || port === DEFAULT_DEV_PORTS.admin) {
    targetPort = DEFAULT_DEV_PORTS[target]
  } else if (port === DEFAULT_COMPOSE_PORTS.member || port === DEFAULT_COMPOSE_PORTS.admin) {
    targetPort = DEFAULT_COMPOSE_PORTS[target]
  } else if (port === DEFAULT_LOCAL_DEMO_PORTS.member || port === DEFAULT_LOCAL_DEMO_PORTS.admin) {
    targetPort = DEFAULT_LOCAL_DEMO_PORTS[target]
  } else {
    return ''
  }
  return `${location.protocol}//${location.hostname}:${targetPort}/?portal=${target}`
}

/** 给显式配置的公开地址补上 `?portal=` 覆盖；已带该参数或非法地址时原样返回。 */
function withPortalQuery(url: string, target: 'member' | 'admin'): string {
  try {
    const parsed = new URL(url)
    if (!parsed.searchParams.has('portal')) parsed.searchParams.set('portal', target)
    return parsed.toString()
  } catch {
    return url
  }
}

/** 无法换算跨端 URL 时的纯文字端口提示。 */
export function crossPortalPortsHint(target: 'member' | 'admin'): string {
  return target === 'admin'
    ? '本地开发 5174/5184 端口 / Compose 8081 端口'
    : '本地开发 5173/5183 端口 / Compose 8080 端口'
}

/** 欢迎页按入口模式呈现的品牌；成员前台刷脸，管理后台账号密码。 */
export interface PortalEntryBranding {
  /** 表单卡标题。 */
  formTitle: string
  /** 表单卡标题下方的一句身份说明；空字符串则不渲染。 */
  formIdentityHint: string
  /** 顶部徽标文字。 */
  badge: string
  /** 首屏主标语（HTML 换行由视图控制，这里只给纯文本两段）。 */
  heroTitle: string
  heroLede: string
  /** 左侧信息栏的三枚承诺胶囊（两端文案不同，避免两个入口长得一样）。 */
  chips: ReadonlyArray<{ icon: string; text: string }>
  /** 凭据 tab 顺序（首个为人脸时，本机已绑定家庭则默认刷脸）。 */
  credentialOrder: ReadonlyArray<'face' | 'password' | 'pin'>
  /** 未绑定人脸时的默认凭据 tab。 */
  defaultCredential: 'face' | 'password' | 'pin'
  /** 是否把账号密码收进“其他方式”。 */
  passwordBehindOtherWays: boolean
  /** 主按钮文案。 */
  ctaLabel: string
  /** 跨端指引文字与目标入口；auto 模式为空。 */
  crossLinkLabel: string
  crossLinkTarget: 'member' | 'admin' | null
}

const MEMBER_BRANDING: PortalEntryBranding = {
  formTitle: '家人登录',
  formIdentityHint: '刷脸进入，或用 PIN 选择家人。',
  badge: '成员前台',
  heroTitle: '我的健康日常',
  heroLede: '刷脸进入，或用 PIN 选择家人。这台电脑需要先由管理员在后台绑定。',
  chips: [
    { icon: 'sun', text: '今天的提醒' },
    { icon: 'scan', text: '拍药盒核对' },
    { icon: 'heart', text: '刷脸就能进' },
  ],
  credentialOrder: ['face', 'pin'],
  defaultCredential: 'pin',
  passwordBehindOtherWays: false,
  ctaLabel: '进入前台',
  crossLinkLabel: '管理员登录',
  crossLinkTarget: 'admin',
}

const ADMIN_BRANDING: PortalEntryBranding = {
  formTitle: '管理员登录',
  formIdentityHint: '新家庭注册后会进入「登录设置」：先给每位家人设 PIN，再按需录入人脸。登录后这台电脑会自动绑定当前家庭。',
  badge: '管理后台',
  heroTitle: '家庭档案与授权',
  heroLede: '使用管理员账号进入。',
  chips: [
    { icon: 'members', text: '成员档案' },
    { icon: 'review', text: '复核入档' },
    { icon: 'lock', text: '安全登录' },
  ],
  credentialOrder: ['password'],
  defaultCredential: 'password',
  passwordBehindOtherWays: false,
  ctaLabel: '进入管理后台',
  crossLinkLabel: '家人登录',
  crossLinkTarget: 'member',
}

/** auto 模式沿用现有欢迎页文案；调用方据此保持原渲染分支。 */
export function portalEntryBranding(mode: PortalEntryMode): PortalEntryBranding | null {
  if (mode === 'member') return MEMBER_BRANDING
  if (mode === 'admin') return ADMIN_BRANDING
  return null
}

/** 入口/门户不匹配时的用户可读提示。 */
export function portalEntryConflictNotice(
  conflict: PortalEntryConflict,
  context: { afterCreate?: boolean } = {},
): {
  message: string
  crossLinkLabel: string
  crossLinkTarget: 'member' | 'admin'
} {
  if (conflict === 'need-admin-entry') {
    if (context.afterCreate) {
      return {
        message: '家庭已创建。请到管理后台「登录设置」为每位家人设置六位数字密码，然后再回成员前台登录。',
        crossLinkLabel: '去管理后台',
        crossLinkTarget: 'admin',
      }
    }
    return {
      message: '这是成员前台。当前账号是管理员，请改用管理后台。',
      crossLinkLabel: '去管理后台',
      crossLinkTarget: 'admin',
    }
  }
  return {
    message: '这是管理后台。当前账号是家庭成员，请改用成员前台。',
    crossLinkLabel: '去成员前台',
    crossLinkTarget: 'member',
  }
}
