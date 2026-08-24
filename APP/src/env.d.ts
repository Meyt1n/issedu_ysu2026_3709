/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}

// MOB-142：vite define 注入的构建信息（见 vite.config.ts）
declare const __APP_VERSION__: string
declare const __BUILD_TIME__: string
declare const __BUILD_COMMIT__: string
