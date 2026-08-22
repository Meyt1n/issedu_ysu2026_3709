/**
 * MOB-142：构建信息（版本、构建时间、源码提交哈希）。
 *
 * 三个值全部由 vite define 在构建期注入（vite.config.ts），
 * 页面只展示可追溯事实，不再使用无法证明来源的固定版本文案。
 */
export interface AppBuildInfo {
  version: string
  builtAt: string
  commit: string
}

export function appBuildInfo(): AppBuildInfo {
  return {
    version: typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : 'unknown',
    builtAt: typeof __BUILD_TIME__ === 'string' ? __BUILD_TIME__ : '',
    commit: typeof __BUILD_COMMIT__ === 'string' ? __BUILD_COMMIT__ : 'unknown',
  }
}

/** 面向"关于"区的单行摘要；缺失信息原样显示 unknown，不编造。 */
export function buildInfoLine(): string {
  const info = appBuildInfo()
  const builtAt = info.builtAt ? new Date(info.builtAt).toLocaleString('zh-CN', { hour12: false }) : 'unknown'
  return `v${info.version} · 构建 ${builtAt} · 提交 ${info.commit}`
}
