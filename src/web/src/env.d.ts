/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 生产构建里显示「模型实验室」等研发入口；默认隐藏（HCT-439 阶段三）。 */
  readonly VITE_SHOW_ADVANCED_LAB?: string
  /** 生产构建里显示「开发演示」登录入口；本地教学 Compose 构建默认开启。 */
  readonly VITE_SHOW_DEV_LOGIN?: string
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}
