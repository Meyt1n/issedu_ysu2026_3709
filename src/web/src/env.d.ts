/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 入口模式：member=成员前台、admin=管理后台；缺省 auto（HCT-453）。 */
  readonly VITE_PORTAL_MODE?: string
  /** 成员前台公开地址（跨端链接用）；缺省按当前端口换算 5173/8080。 */
  readonly VITE_MEMBER_PORTAL_URL?: string
  /** 管理后台公开地址（跨端链接用）；缺省按当前端口换算 5174/8081。 */
  readonly VITE_ADMIN_PORTAL_URL?: string
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}
