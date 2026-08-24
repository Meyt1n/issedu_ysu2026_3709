# MOB-151 PWA 安装、更新提示与缓存恢复生命周期

- 需求：NFR-04、NFR-06、NFR-07
- Issue：[Issue #236](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/236)
- 状态：已实现，真实 Chromium Android、低存储、发布回滚和 Android WebView 验收待具备对应设备/发布环境后执行
- 负责人：ry12-20
- 风险：R2。浏览器安装提示由操作系统与浏览器控制；本 Story 不能保证每个浏览器都会触发安装事件。
- 允许修改目录：`APP/public/manifest.webmanifest`、`APP/public/sw.js`、`APP/src/pwa/`、`APP/src/components/PwaLifecycleNotice.vue`、`APP/src/App.vue`、测试、`APP/README.md`、本 Story。

## 用户价值

使用者能理解当前是否可以安装、何时有新版本可用、离线为什么不显示动态健康数据，以及如何在旧 shell 或缓存损坏时恢复。更新不会在操作中自动刷新，恢复也不会影响服务端事实。

## 范围

- 提供 `beforeinstallprompt` 触发的可关闭、可读屏安装入口；未提供该事件时，给出浏览器菜单安装/添加主屏幕指引。
- manifest 提供独立启动、名称、颜色、纵向方向、192px/512px PNG 和 SVG 后备图标。
- Service Worker 安装新版本后保持 waiting；只有使用者点按“刷新更新”才接收 `HCT_ACTIVATE_UPDATE` 并激活。
- 更新提示明确提示不要在提交操作时刷新，且显示可定位的 shell 版本。
- 提供 shell 恢复操作：仅删除 `hct-mobile-shell-*` 缓存，重新加载页面。
- 离线导航只回退至 shell；静态脚本、样式、图片、字体、manifest 可以缓存。动态接口在离线时保持不可用。
- 不支持 Service Worker 的浏览器继续沿普通 Web 路径工作，并说明能力限制。

## 非目标

- 不实现浏览器和操作系统实际安装 UI。
- 不实现推送通知、后台同步、客户端提醒或客户端健康数据持久化。
- 不将 API 响应、健康正文、图片、凭据、风险详情写入 Cache Storage。
- 不宣称已完成真实 Android WebView、低存储或生产回滚演练。

## Given / When / Then

### 正常路径

- Given 兼容 Chromium 触发 `beforeinstallprompt`，When 使用者选择安装，Then 显示“安装”按钮并调用浏览器原生安装流程；使用者可以关闭提示。
- Given 新 Service Worker 已下载，When 当前页面仍由旧 worker 控制，Then 显示更新提示，不自动激活新 worker；When 使用者在无写操作时点击“刷新更新”，Then 向 waiting worker 发送激活消息并在 controller 切换后刷新。
- Given shell 版本可用，When 查看更新提示，Then 可见版本 `2026.08.24`，用于定位刷新后的外壳。

### 边界与失败路径

- Given 浏览器没有 Service Worker，When 使用 APP，Then 不阻断普通网页使用，并显示“普通网页模式”限制说明。
- Given 浏览器有 Service Worker 但未公开安装提示，When 使用 APP，Then 提示使用浏览器菜单的“安装应用”或“添加到主屏幕”。
- Given 离线冷启动到今日、求助、设置或 API 页面，When shell/静态资源已缓存，Then 页面外壳和静态帮助仍可加载；动态健康数据按不可用处理，不把旧数据伪装为当前事实。
- Given shell 旧、缓存损坏或需要发布回滚，When 使用者选择“恢复”，Then 仅清理本应用 `hct-mobile-shell-*` 缓存后重新加载；不会清理服务端健康事实、接口响应或其他站点缓存。
- Given API、`/health`、非 GET 或跨源请求，When Service Worker 接收请求，Then 直接绕过缓存。

### 未授权

- Given 未授权用户访问动态健康接口，When 离线或在线请求失败，Then 由既有 API 鉴权与不可用状态处理；PWA 缓存不保存也不回放任何健康响应。

## 测试

- 单元测试：PWA 支持能力的普通网页降级、安装入口、shell cache 前缀和 API 缓存排除。
- 构建审计：`npm run audit:pwa` 校验 manifest 资源、shell 资源、缓存边界和更新协议。
- 回归命令：`npm run check`、`npm run test`、`npm run build`、`npm run audit:pwa`、`npm run android:sync`。
- 手工待验收：Chromium Android 安装、桌面更新提示、低存储、发布回滚、离线冷启动、Android WebView。

## 回滚

恢复上一版 `manifest.webmanifest`、`sw.js` 与受控静态资源；将 shell cache 名称恢复为上一发布版本。不要通过删除浏览器全部缓存或清理服务端数据回滚。
