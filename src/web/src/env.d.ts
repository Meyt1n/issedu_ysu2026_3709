/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 生产构建里显示「模型实验室」等研发入口；默认隐藏（HCT-439 阶段三）。 */
  readonly VITE_SHOW_ADVANCED_LAB?: string
  /** 生产构建里显示「开发演示」登录入口；本地教学 Compose 构建默认开启。 */
  readonly VITE_SHOW_DEV_LOGIN?: string
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
