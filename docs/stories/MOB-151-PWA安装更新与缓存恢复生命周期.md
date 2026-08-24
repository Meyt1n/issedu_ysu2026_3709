# MOB-151 PWA 安装、更新提示与缓存恢复生命周期

- Issue：[#236](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/236)（Closes）
- 需求绑定：NFR-04 降级可用、NFR-06 可复现、NFR-07 可访问与可理解
- 负责人：zhang（agent: ZCode）；复核人：维护者（merge 即复核）
- 风险等级：R2（只影响 PWA 外壳与更新提示；回滚 = 恢复 v2 外壳缓存名与旧 sw.js）
- 状态：待验收（桌面 Chromium 证据完成；Android WebView/真机验收待设备）

## 用户价值

此前 manifest 只有 SVG 图标（Chromium 安装条件不足），Service Worker 装完即
`skipWaiting` 静默换版，用户无法理解更新、旧外壳与恢复结果。本任务把 PWA
补齐为可发布、可解释、可恢复的安装/更新/缓存生命周期。

## 范围与实现

- **安装资产**：`APP/public/icons/` 新增 PIL 绘制的 PNG 192/512 与 maskable
  变体（延续 SVG 品牌图形：渐变底、屋形轮廓、桃心）；manifest 补 `id`/`scope`
  与全部图标声明。
- **更新生命周期**（`public/sw.js` + `src/stores/pwa.ts` +
  `src/components/PwaUpdateNotice.vue`）：
  - SW 去掉安装即 `skipWaiting`，改为仅响应页面在用户确认后发送的
    `SKIP_WAITING` 消息；激活时照旧清理旧外壳缓存并 `claim`；
  - 外壳缓存名 v2→v3，SHELL 列表补入新图标；
  - 页面侧 `initPwaLifecycle` 注册 SW 并监听 updatefound/installed 与
    已等待 worker，`PwaUpdateNotice` 渲染可关闭、`role=alert` 的更新提示
    （文案说明提交中任务不会被打断、求助入口保持可用、更新后版本可在
    “我的”页定位）；`applyPendingUpdate` 带 controllerchange 一次性护栏，
    不会连环 reload。
- **安装入口与缓存恢复**（`MeView.vue`）：
  - 捕获 `beforeinstallprompt`，“安装到主屏幕”按钮触发系统引导；未触发时
    显示浏览器菜单手动引导文案；可“不再提示”；
  - “清理离线外壳缓存”两步确认（6 秒武装超时），只调用
    `recoverShellCaches` 删除 `hct-mobile-shell` 前缀缓存后刷新；
  - 不支持 Service Worker 的环境显示普通网页路径的能力限制说明。
- **安全边界**：`/api`、`/health`、健康正文、凭据从不进入缓存（既有 fetch
  策略不变，证据脚本复核缓存条目）；更新提示不泄露健康状态、不阻断求助。

## 明确非目标

- 不做后台自动更新、远程推送或静默热切换；
- 不改变数据层/鉴权行为；Android 安装与 WebView 通知链路不在本切片
  （真机验收单列）；
- 不新增任何网络出口。

## 测试与证据

2026-08-24 基于最新 `master`（源码提交 `345b5b2`）复核：

- `npm run audit:pwa` 通过：9 个外壳资源、5 个图标资源均存在，非 GET/跨源/`/api`/`/health` 均不会进入缓存；
- `npm run test -- --run src/stores/pwa.test.ts` 通过（12 项）；
- `node scripts/pwa-lifecycle.mjs` 通过：安装资源、离线冷启动、外壳缓存丢失安全回退、更新提示和用户确认接管均完成浏览器证据；
- 修正 `audit-pwa.mjs` 对 Service Worker 注册的检查，使其识别当前 `initPwaLifecycle()` 封装，同时继续校验实际 `.register('/sw.js')` 调用。

- 单元测试 `APP/src/stores/pwa.test.ts`（12 项）：installed+控制器判定、
  updatefound 流、SKIP_WAITING 派发与一次性刷新护栏、重复确认忽略、
  recoverShellCaches 仅清外壳前缀、安装提示一次性可用与关闭、能力说明。
- `npm run check` / `npm run test`（205 项）/ `npm run build`：全部通过；
  `npm run android:sync`：完成。
- 生命周期证据 `APP/scripts/pwa-lifecycle.mjs`（node scripts/pwa-lifecycle.mjs，
  PASS）：
  - manifest + 4 个 PNG 图标全部 200；
  - 缓存审计：仅 `hct-mobile-shell-v3`（9 条），无 `/api`/`/health` 条目；
  - 离线冷启动：外壳与演示数据可用（`MOB-151-offline-cold-start.png`）；
  - 外壳缓存丢失且离线：安全回退提示、无旧健康数据
    （`MOB-151-shell-recovery-fallback.png`）；
  - 部署新 sw.js：出现更新提示、无静默切换；确认后新 worker activated、
    部署标记可定位（`MOB-151-update-notice.png`）。
- **待设备**：Chromium Android 安装引导、Android WebView 更新/离线与低存储
  场景未在真机执行，按仓库惯例标注待验收，不冒充完成。

## 部署影响与回滚

- 无迁移、无新依赖；manifest/sw.js/图标为静态资产变更。
- 回滚：恢复上一版 `hct-mobile-shell-v2` 缓存名与旧 sw.js（自动 skipWaiting
  行为），移除更新提示组件与安装/恢复入口；外壳缓存可由用户在浏览器清除，
  或等待 v2 激活时自动清理 v3。

## 已知限制

- 安装引导是否弹出取决于浏览器策略（桌面 Chromium 常不触发），页面以手动
  引导文案兜底；`beforeinstallprompt` 之外无法强制安装。
- 低存储场景的浏览器行为不可控，缓存恢复入口提供的是“安全重置”而非存储
  保障。
