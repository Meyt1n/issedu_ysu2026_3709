# MOB-150：Android 本地备份、网络与系统能力安全加固

- Issue：[#237](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/237)
- 需求：NFR-01、NFR-02、NFR-06
- 状态：进行中（静态策略、自动审计、本地构建、真机关键路径和模拟器通知/多用户隔离证据完成；真实设备迁移还原与受控 HTTPS 证书仍待补齐）
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
- 权限：源码主 Manifest 只保留 `INTERNET`；最终合并 Manifest 由 `@capacitor/local-notifications` 带入并实际使用 `POST_NOTIFICATIONS`、`RECEIVE_BOOT_COMPLETED`、`WAKE_LOCK`、`SCHEDULE_EXACT_ALARM` 和 AndroidX 动态接收器权限。相机/文件使用用户主动触发的系统选择器，拨号只打开 `tel:` 界面，不申请相机、电话或存储敏感权限；
- 自动审计：校验源码 Manifest、备份/迁移、网络策略和权限白名单；若已构建 Release，则进一步检查最终合并 Manifest，避免只审计源码 Manifest 而漏掉插件权限，并记录 APK 哈希。

Android 静态网络配置无法表达“任意 RFC1918/ULA 地址可明文、任意公网地址不可明文”的 CIDR 动态规则，因此不能在 Release 中全局打开 cleartext。Debug 平台能力与 APP 层校验组合保留局域网联调，Release 则在 APP 和平台两层只允许 HTTPS。

## Given / When / Then

- Given Release/Main 构建；When 检查 Manifest 和 data extraction 规则；Then 系统备份与设备迁移均不能导出应用私有域。
- Given Release/Main 构建；When 请求 HTTP 地址；Then APP 地址校验和 Android 网络策略均 fail-closed；HTTPS 继续可用。
- Given Android Debug 联调；When 输入家庭私网 HTTP；Then Debug 平台允许请求，APP 仍拒绝公网 HTTP、凭据、查询参数和恶意协议。
- Given 检查系统权限；When 审计源码和最终合并 Manifest；Then 源码基线只存在 `INTERNET`，合并结果只包含提醒插件所需权限，没有未使用的相机、电话或存储权限；通知权限在用户主动开启本地提醒时按系统对话框处理。
- Given 升级、自动恢复或设备迁移；When应用启动；Then旧身份、联系人、服务器地址和 WebView 私有数据不应被系统恢复；该项须以真机/模拟器备份命令补充最终证据。

## 自动与构建证据

### 2026-08-25 `codex/mob-150-device-verification` 真机复核

- 设备：荣耀 AAP-AN00，Android 16 / API 36，arm64-v8a；设备用户列表为机主 `0` 与分身 `128`，应用仅安装在机主用户；
- Debug APK：`com.homecaretwin.companion`，`targetSdkVersion=36`；SHA-256 `7B6F7E3A0EB82FBD961EB952F2FCE071366E1C93159F0F092F976826E7733FD2`；Release unsigned APK SHA-256 `38046BFF04AF29814CD2798A098783B83944AD336C2DFEAFAF790CC501F7F383`；APK 不提交仓库；
- 首次启动展示“隐私与健康数据边界”告知；确认后通知权限出现系统授权对话框。拒绝/永久拒绝在当前荣耀系统授权器上未形成稳定可复现的最终状态，不能把一次对话框出现冒充拒权完成；
- 相机入口进入荣耀系统相机，未出现应用 `CAMERA` 权限对话框；相册入口进入 Android Photo Picker，展示“安全访问图库/仅可访问本次选择的照片和视频”，未申请存储权限；
- `adb shell bmgr backupnow com.homecaretwin.companion` 返回 `Backup is not allowed`；切换到 D2D transport 后，系统返回 transport 无法处理该包，随后已切回原云备份 transport。说明应用未被允许写入本机备份，但当前设备没有可完成的真实设备迁移/还原演练入口；
- 当前应用数据为虚构演示数据；卸载后重新安装 Debug APK，首次安装时间重置且重新出现首启隐私告知，没有恢复旧登录/联系人/服务器设置的证据；
- `npm run audit:android-security`、`npm run check`、`npm run test`（30 个文件 / 246 个测试）、`npm run build`、`npm run android:sync:debug`、Gradle Debug/Release 合并清单和 Debug/Release 构建均通过；

### 2026-08-25 Android 模拟器补充复核

- 设备：Android 15 / API 35 模拟器 `emulator-5554`；仅使用虚构演示数据；
- 清除应用数据后首次启动出现系统通知授权对话框，选择拒绝后 `POST_NOTIFICATIONS` 为 `granted=false`，应用仍回到 `MainActivity` 正常运行；
- 将同一权限置为系统 `USER_FIXED` 永久拒绝后强制停止并重启应用，仍直接进入 `MainActivity`，未再次弹出授权对话框；
- 创建临时次用户 `10`，为该用户安装同一 APK 并启动应用：应用运行在 `u10`，数据目录为 `/data/user/10/com.homecaretwin.companion`，机主仍使用独立的 `/data/user/0/com.homecaretwin.companion`；验证后停止并删除临时用户，模拟器恢复为仅机主用户；
- 该模拟器证据补齐通知拒绝/永久拒绝和多用户启动隔离；真实设备迁移还原仍因没有可控 D2D/云备份恢复源无法完成，受控 HTTPS 证书联调仍需专用证书环境。

### 2026-08-24 最新 `master` 复核

- `npm run audit:android-security` 通过：Release 禁止明文流量，Debug 仅开放受控明文，备份/设备迁移排除，源码 Manifest 仅声明 `android.permission.INTERNET`；构建后审计最终合并 Manifest 的提醒插件权限白名单；
- `npm run check` 通过；`npm run test` 通过（26 个文件 / 219 个测试）；
- `npm run build`、`npm run android:sync` 与 `npm run android:sync:debug` 均通过；
- 本次复核未生成或提交 APK、签名材料、备份数据或日志；Android 真机备份/迁移/拒权和安装验收仍需维护者在目标设备完成。

- `npm run audit:android-security`：静态 Manifest、网络、备份、设备迁移和权限白名单审计。
- `npm run check`、`npm run test`、`npm run build`、`npm run android:sync`、`npm run android:sync:debug`。
- `gradlew processDebugMainManifest` / `processReleaseMainManifest`：检查合并后的 Debug/Release Manifest。
- `gradlew assembleDebug` / 可用环境下 `assembleRelease`，对产物执行 SHA-256；不提交 APK、签名材料或本机路径。

2026-08-24 基于最新 `master`（源码提交 `345b5b2`）复核：

- `npm run audit:android-security` 通过：Release 禁止明文、Debug 仅受控开放明文、备份与设备迁移排除、主 Manifest 仅声明 `android.permission.INTERNET`；
- `npm run check`、`src/utils/serverUrl.test.ts` 定向测试（3 项）和 `npm run build` 通过；
- Android 真机备份/迁移、拒权和 APK 哈希仍需 JDK 21–24 与设备环境，未将静态审计冒充最终真机验收。

本次环境已完成 `aapt2` 对新增 XML 资源的编译和 Debug Web 产物同步；Gradle 首次下载发行包后因本机 JBR 为 25.0.2，而仓库固定 Gradle 8.14.3 只接受 JDK 21–24，`assembleDebug` 在 settings 阶段停止。脚本现已提前检测并给出明确提示；换用 JDK 21–24 后应重新执行原生命令。

## 交付轨迹（补记）

首版实现走 PR [#253](https://github.com/Meyt1n/issedu_ysu2026_3709/pull/253)，但它的 base 误选成 `codex/mob-138-140-foundation` 而不是 `master`；而那条分支的 PR [#249](https://github.com/Meyt1n/issedu_ysu2026_3709/pull/249) 早在 #253 之前就已合并，之后再没往 master 合过。结果本 Story 的全部产物（Android 备份/迁移/网络策略、`audit-android-security.mjs`、地址策略与本文件）从未出现在 `master` 上，#237 也因此一直 open。

2026-08-21 从当前 `master` 重新切分支、cherry-pick 原提交并解决与 MOB-133 的冲突后重新提交。冲突只在两处，均为叠加而非取舍：`APP/package.json` 的脚本表（保留 `verify:android-a11y-evidence`，补回 `android:sync:debug` 与 `audit:android-security`）、`APP/src/views/MeView.vue` 的 setup 段（保留 MOB-133 的会话与 PIN 状态，补回地址策略文案）。

**对 MOB-133 联调复现方式的影响：** 本 Story 让发布构建拒绝私网明文 HTTP，因此 MOB-133 那批用 `vite preview`（production 模式）连 `http://127.0.0.1:18812` 取证的步骤在本 PR 之后不再适用；复现时请改用 `npm run dev`，或 `vite build --mode android-debug` 后再 preview。已取得的证据本身仍然有效，它们是在本变更之前采集的。

## 未完成证据与回滚

- 真实设备迁移还原和受控 HTTPS 证书联调仍需在专用测试设备/环境执行；完成前 Issue 保持进行中。通知拒绝/永久拒绝和多用户启动隔离已由 Android 15 模拟器补充验证。
- PR 未合并前关闭分支；合并后 revert 本 PR，恢复上一份经验证的 Manifest/网络配置和构建脚本。回滚不得重新启用 Release 全局明文或系统备份。
