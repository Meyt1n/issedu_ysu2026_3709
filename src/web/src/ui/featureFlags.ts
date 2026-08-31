/**
 * HCT-439 门户功能开关。
 *
 * - 模型实验室等研发入口只在开发环境（`vite dev`）或显式设置
 *   `VITE_SHOW_ADVANCED_LAB=true` 的构建里出现，普通家庭的生产构建默认隐藏。
 * HCT-498 起 Web 登录固定为正式账号密码，不再提供开发身份开关。
 */
export const SHOW_ADVANCED_LAB: boolean =
  import.meta.env.DEV || import.meta.env.VITE_SHOW_ADVANCED_LAB === 'true'
