/**
 * HCT-439 门户功能开关。
 *
 * - 模型实验室等研发入口只在开发环境（`vite dev`）或显式设置
 *   `VITE_SHOW_ADVANCED_LAB=true` 的构建里出现，普通家庭的生产构建默认隐藏。
 * - 「开发演示」登录入口同理由 `VITE_SHOW_DEV_LOGIN` 控制；本地教学
 *   Compose 镜像在构建参数里默认开启，配合后端 `ALLOW_DEV_ACTOR_HEADER`。
 *   后端在生产环境会拒绝开发身份头，这里只是同时收掉前端入口。
 */
export const SHOW_ADVANCED_LAB: boolean =
  import.meta.env.DEV || import.meta.env.VITE_SHOW_ADVANCED_LAB === 'true'

export const SHOW_DEV_LOGIN: boolean =
  import.meta.env.DEV || import.meta.env.VITE_SHOW_DEV_LOGIN === 'true'
