# MOB-506 Android 私网 HTTP 真机验收记录（2026-09-01）

> 对应 Issue [#506](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/506)。本记录验证 Android Debug 壳在保留 `https://localhost` 页面源的前提下，能够访问受控家庭局域网 HTTP 服务；不放宽 Release 的 HTTPS-only 边界，也不把本地合成服务写成生产后端证据。

## 环境与数据边界

| 项目 | 记录 |
| --- | --- |
| 设备 | 荣耀 AAP-AN00，Android 16 |
| WebView | Android System WebView 138.0.7204.179 |
| 屏幕/应用 | 1272×2800；`com.homecaretwin.companion`，versionName `1.0`、targetSdk `36` |
| 已安装包 | Debug APK，`lastUpdateTime=2026-08-31 11:40:03`；安装时间早于本次源码同步，不能视为最新发布候选包 |
| 网络 | 手机与电脑处于同一 `172.16.30.0/24` 局域网；服务端地址使用 `http://172.16.30.29:8000` |
| 服务端 | 电脑临时启动的受控合成 HTTP fixture，仅提供 `/health` 和 `/api/v1/meta/capabilities`，响应版本 `synthetic-506` |
| 数据 | 不含账号、token、家庭健康数据、药品图片或真实 API 响应 |

## 验收步骤与结果

1. 在电脑 `0.0.0.0:8000` 启动合成 fixture，访问 `http://127.0.0.1:8000/health` 和 `http://172.16.30.29:8000/health` 均返回 HTTP 200。
2. 使用 ADB 从手机探测 `172.16.30.29:8000`，TCP 连接返回成功。
3. 启动 App，确认活动页面来源为 `https://localhost/#/`。
4. 通过该 App 的活动 WebView 只读执行跨源请求：

   - `http://172.16.30.29:8000/health` → `ok=true`、`status=200`、正文 `{"status":"ok","service":"controlled-http-fixture","version":"synthetic-506"}`；
   - `http://172.16.30.29:8000/api/v1/meta/capabilities` → `ok=true`、`status=200`，能力响应含 `vision-task-video`。

| 检查项 | 观察结果 | 结论 |
| --- | --- | --- |
| 手机到局域网端口 | ADB TCP 探测成功 | 通过 |
| HTTPS 页面请求 HTTP 私网地址 | WebView `fetch` 正常解析为 200，无 mixed-content 错误 | 通过 |
| `/health` 响应 | 合成 fixture 返回 `status=ok` | 通过（受控 smoke） |
| `/api/v1/meta/capabilities` 响应 | 合成 fixture 返回 `vision-task-video` | 通过（受控 smoke） |
| Release 安全边界 | `npm run audit:android-security`：`releaseCleartext=false`、备份/设备转移排除 | 通过 |

## 代码边界复核

- `MainActivity` 仅在 `BuildConfig.DEBUG` 下设置 `MIXED_CONTENT_ALWAYS_ALLOW`；Release 不执行该分支。
- `android/app/src/debug/res/xml/network_security_config_debug.xml` 只随 Debug 变体提供明文局域网覆盖；主 Manifest 和 Release 网络配置保持 `cleartextTrafficPermitted=false`。
- `serverUrl.ts` 仍只接受回环、局域网和 `.local` 主机的 Debug HTTP；公网 HTTP、凭据、查询参数和其他协议继续拒绝。
- 本次未修改运行时代码；修复代码已在当前 `master` 基线中，本记录补充其真机行为证据。

## 结论与限制

MOB-506 描述的 Android Debug WebView mixed-content 软件阻断已解除，并在荣耀真机上通过受控 HTTP smoke。该证据足以证明“Debug 壳可访问受控私网 HTTP”这一 Issue 范围，但不等同于真实家庭服务器、登录会话或视频上传端到端验收。

HCT-414/#246 仍需在同一最终候选 APK 上继续验证真实文件选择器 MIME、手机发起的视频上传、相机 HEVC 抽帧和服务端受控错误；Release 发布仍必须使用 HTTPS-only。

回滚方式：移除 Debug-only WebView mixed-content 分支和 Debug 网络配置即可恢复原有“所有 WebView 明文请求均拒绝”行为；Release 配置不受本次证据影响。
