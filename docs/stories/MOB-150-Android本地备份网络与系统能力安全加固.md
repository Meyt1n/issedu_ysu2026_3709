# MOB-150：Android 本地备份、网络与系统能力安全加固

- Issue：[#237](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/237)
- 需求：NFR-01、NFR-02、NFR-06
- 状态：进行中（静态策略、自动审计和本地构建证据完成；Android 真机备份/迁移/拒权与安装验收待执行）
- 负责人：Shen-huang-123
- 复核人：维护者合并时完成最终复核
- 风险：R3（错误的备份或网络配置可能恢复身份/联系人，或把健康请求发送到明文公网）
- 依赖：[#224](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/224)、[#231](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/231)、[#225](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/225)
- 允许修改：`APP/android/`、Capacitor 配置、服务器地址策略、构建/审计脚本、测试、`APP/README.md`、本 Story 和需求追踪矩阵

## 用户价值

发布 Android 包不会把应用私有存储交给系统云备份或设备迁移，也不会全局允许明文网络；受控 Debug 包仍可连接家庭局域网 HTTP，且 APP 层继续拒绝公网 HTTP。应用只声明当前真正使用的系统权限。

## 决策与范围

- Main/Release：`allowBackup=false`，全量排除旧版 full-backup 和 Android 12+ cloud-backup/device-transfer 域；`usesCleartextTraffic=false` 且 base network policy 拒绝明文流量；
- Debug：独立 manifest/network config 允许明文流量，仅配合 `android-debug` Web 构建使用；APP 地址校验仍只接受 localhost/`.local`/私网 IPv4/IPv6，拒绝公网 HTTP；
- PWA/Vite production 与 Android Release：APP 地址策略只允许 HTTPS；开发模式和 `android-debug` 模式才开放私网 HTTP；
- 权限：主 Manifest 只保留 `INTERNET`。相机/文件使用用户主动触发的系统选择器，拨号只打开 `tel:` 界面，当前不申请相机、电话、通知或存储敏感权限；
- 自动审计：校验 manifest、备份/迁移、网络策略和权限白名单，构建后再检查合并 Manifest 与 APK 哈希。

Android 静态网络配置无法表达“任意 RFC1918/ULA 地址可明文、任意公网地址不可明文”的 CIDR 动态规则，因此不能在 Release 中全局打开 cleartext。Debug 平台能力与 APP 层校验组合保留局域网联调，Release 则在 APP 和平台两层只允许 HTTPS。

## Given / When / Then

- Given Release/Main 构建；When 检查 Manifest 和 data extraction 规则；Then 系统备份与设备迁移均不能导出应用私有域。
- Given Release/Main 构建；When 请求 HTTP 地址；Then APP 地址校验和 Android 网络策略均 fail-closed；HTTPS 继续可用。
- Given Android Debug 联调；When 输入家庭私网 HTTP；Then Debug 平台允许请求，APP 仍拒绝公网 HTTP、凭据、查询参数和恶意协议。
- Given 检查系统权限；When 审计主 Manifest；Then 只存在 `INTERNET`，没有未使用的相机、电话、通知或存储权限。
- Given 升级、自动恢复或设备迁移；When应用启动；Then旧身份、联系人、服务器地址和 WebView 私有数据不应被系统恢复；该项须以真机/模拟器备份命令补充最终证据。

## 自动与构建证据

- `npm run audit:android-security`：静态 Manifest、网络、备份、设备迁移和权限白名单审计。
- `npm run check`、`npm run test`、`npm run build`、`npm run android:sync`、`npm run android:sync:debug`。
- `gradlew processDebugMainManifest` / `processReleaseMainManifest`：检查合并后的 Debug/Release Manifest。
- `gradlew assembleDebug` / 可用环境下 `assembleRelease`，对产物执行 SHA-256；不提交 APK、签名材料或本机路径。

本次环境已完成 `aapt2` 对新增 XML 资源的编译和 Debug Web 产物同步；Gradle 首次下载发行包后因本机 JBR 为 25.0.2，而仓库固定 Gradle 8.14.3 只接受 JDK 21–24，`assembleDebug` 在 settings 阶段停止。脚本现已提前检测并给出明确提示；换用 JDK 21–24 后应重新执行原生命令。

## 交付轨迹（补记）

首版实现走 PR [#253](https://github.com/Meyt1n/issedu_ysu2026_3709/pull/253)，但它的 base 误选成 `codex/mob-138-140-foundation` 而不是 `master`；而那条分支的 PR [#249](https://github.com/Meyt1n/issedu_ysu2026_3709/pull/249) 早在 #253 之前就已合并，之后再没往 master 合过。结果本 Story 的全部产物（Android 备份/迁移/网络策略、`audit-android-security.mjs`、地址策略与本文件）从未出现在 `master` 上，#237 也因此一直 open。

2026-08-21 从当前 `master` 重新切分支、cherry-pick 原提交并解决与 MOB-133 的冲突后重新提交。冲突只在两处，均为叠加而非取舍：`APP/package.json` 的脚本表（保留 `verify:android-a11y-evidence`，补回 `android:sync:debug` 与 `audit:android-security`）、`APP/src/views/MeView.vue` 的 setup 段（保留 MOB-133 的会话与 PIN 状态，补回地址策略文案）。

**对 MOB-133 联调复现方式的影响：** 本 Story 让发布构建拒绝私网明文 HTTP，因此 MOB-133 那批用 `vite preview`（production 模式）连 `http://127.0.0.1:18812` 取证的步骤在本 PR 之后不再适用；复现时请改用 `npm run dev`，或 `vite build --mode android-debug` 后再 preview。已取得的证据本身仍然有效，它们是在本变更之前采集的。

## 未完成证据与回滚

- Android 真机首次使用、拒绝/永久拒绝、卸载重装、`bmgr` 备份恢复、设备迁移、多用户和受控 HTTPS 证书联调仍需维护者执行；完成前 Issue 保持进行中。
- PR 未合并前关闭分支；合并后 revert 本 PR，恢复上一份经验证的 Manifest/网络配置和构建脚本。回滚不得重新启用 Release 全局明文或系统备份。
