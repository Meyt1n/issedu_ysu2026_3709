# MOB-127 PWA 离线审计

- Issue：[#182](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/182)
- 负责人：ry12-20
- 允许修改：`APP/`、`docs/stories/`
- 关联需求：NFR-04、NFR-06、NFR-08

## 验收结论

- [x] 生产入口只在生产构建中注册 `/sw.js`，开发环境不会因为 Service Worker 影响热更新。
- [x] 应用外壳、manifest、图标和两套氛围背景在构建产物中存在，并由 Service Worker 预缓存。
- [x] 页面导航采用 network-first；网络不可用时回退到缓存的 `/` 外壳，保证已安装应用仍能打开。
- [x] 静态资源采用 cache-first，网络成功回源后写入当前版本缓存。
- [x] 非 GET 请求、跨源请求、`/api` 和 `/health` 请求均绕过缓存，不把健康数据和家庭健康数据写入 Service Worker Cache Storage。
- [x] 构建后审计脚本会检查以上策略，缺少资源或出现缓存边界回归时返回非零退出码。

## 实现内容

`APP/scripts/audit-pwa.mjs` 是一个不依赖浏览器的构建后审计器。

它读取 `public/sw.js`、`public/manifest.webmanifest` 和生产 `dist/`，检查 Service Worker 注册入口、外壳预缓存清单、manifest 图标、离线导航回退、静态资源缓存优先策略和接口缓存禁令。

审计器不请求家庭服务器，也不读取数据库，因此不会接触健康数据。

这项检查的目标是验证缓存策略本身，而不是把 API 响应伪装成离线数据。

## 验证命令

在 `APP/` 目录执行：

```powershell
npm run audit:pwa
npm run check
npm run test
npm run build
```

其中 `npm run audit:pwa` 会先生成生产构建，再检查 `dist/` 和 Service Worker 源码。

预期输出包含外壳资源数量、缓存边界结论和导航/静态资源策略结论。

## 手工浏览器复核

1. 使用生产静态服务器打开应用并完成一次首屏加载。
2. 在浏览器开发者工具中确认 `/sw.js` 已注册并处于 activated 状态。
3. 关闭网络后重新访问应用根路径，确认应用外壳仍可显示。
4. 在网络面板中确认 `/api` 和 `/health` 请求没有被 Service Worker 以缓存响应替代。
5. 恢复网络后重新加载，确认导航可以回到 network-first 路径。

这份手工步骤只验证壳和缓存边界。

离线时不展示过期的家庭健康数据，是本项目的安全约束，而不是需要通过缓存实现的功能。

## 回滚

若生产环境出现 Service Worker 更新问题，可回滚本 PR；浏览器端会在下一次注册时清理旧的 `hct-mobile-shell-*` 缓存版本。
