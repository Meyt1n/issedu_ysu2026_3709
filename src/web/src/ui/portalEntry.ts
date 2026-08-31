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

/** 当前页面的入口模式；首次调用时从环境解析并缓存。 */
export function activePortalEntryMode(): PortalEntryMode {
  if (activeEntryMode === null) activeEntryMode = resolvePortalEntryMode(readEnvironmentSignals())
  return activeEntryMode
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

/** 欢迎页按入口模式呈现的品牌；所有凭据仍走正式认证接口。 */
export interface PortalEntryBranding {
  /** 表单卡标题。 */
  formTitle: string
  /** 表单卡标题下方的一句身份说明。 */
  formIdentityHint: string
  /** 顶部徽标文字。 */
  badge: string
  /** 首屏主标语（HTML 换行由视图控制，这里只给纯文本两段）。 */
  heroTitle: string
  heroLede: string
  /** 左侧信息栏的三枚承诺胶囊（两端文案不同，避免两个入口长得一样）。 */
  chips: ReadonlyArray<{ icon: string; text: string }>
  /** 凭据 tab 顺序（首个为默认推荐）。 */
  credentialOrder: ReadonlyArray<'face' | 'pin' | 'password'>
  /** 未绑定人脸时的默认凭据 tab。 */
  defaultCredential: 'face' | 'pin' | 'password'
  /** 是否把账号密码收进“其他方式”（成员前台默认不隐藏）。 */
  passwordBehindOtherWays: boolean
  /** 主按钮文案。 */
  ctaLabel: string
  /** 跨端指引文字与目标入口；auto 模式为空。 */
  crossLinkLabel: string
  crossLinkTarget: 'member' | 'admin' | null
}

const MEMBER_BRANDING: PortalEntryBranding = {
  formTitle: '家庭成员前台 · 正式登录',
  formIdentityHint: '使用分配给本人的正式账号密码登录；也可使用已配置的人脸或数字密码，只查看自己的提醒、记录与帮助。',
  badge: '成员前台 · 每位家人自己的健康日常',
  heroTitle: '我的健康日常，安全登录后查看',
  heroLede:
    '这里是每位家人自己的个人前台：使用正式账号密码进入，看今天的提醒、拍药盒交给家人核对。管理档案和授权的事，交给家庭管理后台。',
  chips: [
    { icon: 'sun', text: '今天的提醒，一眼看到' },
    { icon: 'scan', text: '拍个药盒，家人核对' },
    { icon: 'heart', text: '账号、数字密码、人脸均可用' },
  ],
  credentialOrder: ['face', 'pin', 'password'],
  defaultCredential: 'pin',
  passwordBehindOtherWays: false,
  ctaLabel: '登录成员前台',
  crossLinkLabel: '我是家庭管理员，去管理后台',
  crossLinkTarget: 'admin',
}

const ADMIN_BRANDING: PortalEntryBranding = {
  formTitle: '家庭管理后台 · 管理员登录',
  formIdentityHint: '使用正式账号密码以家庭管理员身份进入：管理的是整个家庭的档案、复核与授权，不是某位家人的个人前台。',
  badge: '家庭管理后台 · 成员档案 / 复核 / 授权',
  heroTitle: '管好一家人的健康档案与授权',
  heroLede: '使用管理员账号密码登录，处理成员档案、药品复核、用药安全与授权；家人日常请使用成员前台。',
  chips: [
    { icon: 'members', text: '成员档案，集中管理' },
    { icon: 'review', text: '识别候选，复核后才入档' },
    { icon: 'key', text: '谁能看什么，授权说了算' },
  ],
  credentialOrder: ['password'],
  defaultCredential: 'password',
  passwordBehindOtherWays: false,
  ctaLabel: '登录管理后台',
  crossLinkLabel: '我是家庭成员，回成员前台',
  crossLinkTarget: 'member',
}

/** auto 模式沿用现有欢迎页文案；调用方据此保持原渲染分支。 */
export function portalEntryBranding(mode: PortalEntryMode): PortalEntryBranding | null {
  if (mode === 'member') return MEMBER_BRANDING
  if (mode === 'admin') return ADMIN_BRANDING
  return null
}

/** 欢迎页「正确进入成员前台」短清单（HCT-456）。 */
export const MEMBER_PORTAL_ENTRY_STEPS: ReadonlyArray<string> = [
  '先启动本地服务，再打开成员前台（开发端口 5173，或 Compose 的 8080）',
  '打开 http://127.0.0.1:5173（Compose 用 http://localhost:8080）',
  '使用家庭成员正式账号密码登录；已配置的人脸或数字密码也可使用；管理员请改去管理后台 5174/8081',
]

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
        message:
          '家庭已创建。创建者是家庭管理员，成员前台不会停留在管理界面。请改用管理后台（5174/8081）完成配置；家人日常再用各自的正式账号密码登录成员前台。',
        crossLinkLabel: '去管理后台登录',
        crossLinkTarget: 'admin',
      }
    }
    return {
      message:
        '这是家庭成员前台。当前账号是家庭管理员（创建家庭的人）。请改用管理后台（5174/8081）登录；若要进本页，请换用家庭成员的正式账号密码。',
      crossLinkLabel: '去管理后台登录',
      crossLinkTarget: 'admin',
    }
  }
  return {
    message:
      '这是家庭管理后台。当前账号是家庭成员。请打开成员前台（5173/8080），使用该成员的正式账号密码登录；不要用管理员账号进成员前台。',
    crossLinkLabel: '回成员前台登录',
    crossLinkTarget: 'member',
  }
}
