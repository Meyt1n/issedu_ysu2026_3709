# Android 演示发布包操作记录

## 产物与范围

- 产物类型：Capacitor Android debug APK，仅用于教学演示。
- 预期路径：`APP/android/app/build/outputs/apk/debug/app-debug.apk`。
- 数据边界：默认使用应用内虚构“演示”数据；联机模式必须由操作者在应用中填入本地可信家庭服务端地址和开发身份。
- 不是生产发布包：未配置应用商店签名、正式登录/PIN、远程运维或真实家庭数据。

## 干净环境前置条件

1. Node.js 与锁定依赖：在 `APP/` 执行 `npm ci`。
2. Android Studio/SDK，设置 `ANDROID_HOME` 为 SDK 目录。
3. JDK 21 或 Android Studio 自带 JBR。构建脚本可用 `-JavaHome` 指定路径。
4. 禁止提交 `android/local.properties`、APK、签名文件、真实局域网 IP、密钥、日志或真实健康数据。

## 构建

```powershell
cd APP
npm run check
npm run test
npm run build
npm run android:sync
powershell -ExecutionPolicy Bypass -File scripts/build-apk.ps1 -JavaHome "<JDK 21 或 Android Studio JBR>"
```

脚本首次运行会仅在本机创建 `android/local.properties`。成功时读取 APK 路径并记录构建命令、JDK/SDK 版本和 Git 提交；不要将 APK 提交到仓库。

## 安装与演示

1. 将 debug APK 传到 Android 测试设备，按设备提示允许安装未知来源应用。
2. 启动后确认页面有“演示”标识；演示数据均为虚构。
3. 需要联机演示时，手机与服务端在同一局域网，服务端地址使用电脑的局域网 IP，例如 `http://192.168.1.10:18800`，不能使用 `localhost`。
4. 在“我的 > 数据来源”配置家庭服务器、开发身份和 `family-care` 访问目的；无授权、服务不可达或接口缺失必须显示真实错误。
5. 视觉候选确认仍转网页端人工复核；风险知晓回写在服务端未提供接口时不可用。

## 回滚

- 安装前：删除设备上的 APK 文件即可。
- 安装后：卸载 debug 应用或安装上一经验证 APK；本地设置可在应用内恢复演示数据。
- 代码：revert 对应 PR。不得通过删除服务端事件、授权或审计记录来回滚客户端发布。

## 本机验证记录（2026-08-17，历史）

| 检查 | 结果 |
| --- | --- |
| `npm run check` | 通过 |
| `npm run test` | 通过，43 tests passed |
| `npm run build` | 通过 |
| `npm run android:sync` | 通过 |
| `scripts/build-apk.ps1` | 阻塞：未发现 `C:\Users\C\AppData\Local\Android\Sdk`，未生成 APK |

本机 `JAVA_HOME` 已设置，但 Android SDK 未安装或未配置。安装 Android Studio SDK 后，设置 `ANDROID_HOME` 到实际 SDK 目录并重跑构建脚本。此记录不构成真机安装或 APK 发布验证。

## 本机复核记录（2026-08-27，历史）

本次复核只使用仓库内虚构演示数据，不上传真实健康数据，也不把浏览器或低端模拟结果当作 Android 真机签收。

| 检查 | 结果 |
| --- | --- |
| `npm run check` | 通过 |
| `npm run test` | 通过，31 个文件 / 282 tests passed |
| `npm run build` | 通过，Vite 生产构建完成 |
| `npm run android:sync` | 通过，Capacitor 8.5.0 同步完成 |
| `npm run privacy:scan` | 通过，未发现签名材料、密钥或异常资源 |
| `npm run audit:android-security` | 通过，Release 明文流量关闭，Release 合并权限已审计 |
| `npm run audit:pwa` | 通过，外壳资源、缓存边界和离线策略通过 |
| `npm run release:manifest -- --out release` | 通过，版本 `0.1.0`、源码提交与 55 个 PWA 产物哈希已生成到未跟踪 `release/` |
| `npm run perf:budget` | 通过，浏览器 PWA 基线与断网恢复均在预算内 |
| `npm run perf:budget:low-end` | 通过，4× CPU / Slow 3G 模拟均在预算内 |
| `npm run test:perf-budget` | 通过 |
| `npm run test:privacy-scan` | 通过 |
| `npm run verify:linkage` | 阻塞：当前未启动受控后端（`127.0.0.1:18800`） |
| `scripts/build-apk.ps1` | 阻塞：本机未找到 JDK 21–24，未生成 APK |
| `npm run verify:android-a11y-evidence` | 阻塞：缺少 Android 真机、TalkBack、WebView 和 APK 哈希签收 |
| `npm run verify:android-voice-evidence` | 阻塞：缺少 Android 真机语音矩阵和设备元数据 |

本记录证明的是 PWA/Capacitor 同步和静态安全边界可复跑；它不构成 Android 安装、相机权限、通知、TalkBack、TTS、后台恢复或真实后端联机的通过。补齐 JDK、受控 HTTPS 后端和 Android 真机后，必须重跑本节命令并填写未提交的受控发布记录。

## 本机发布候选复核（2026-08-28）

本次基于最新 `master`（源码基线 `c0640ca`）及 Android 构建配置修复执行，使用仓库虚构演示数据。APK 和签名材料只保存在本机，未提交仓库。

| 检查 | 结果 |
| --- | --- |
| `npm run check` | 通过 |
| `npm run test` | 通过，32 个文件 / 290 tests |
| `npm run build` | 通过，Vite 生产构建完成 |
| `npm run android:sync` | 通过，Capacitor 8.5.0 同步完成 |
| `scripts/build-apk.ps1` | 通过，JDK 21 + Android SDK 生成 debug APK |
| APK 产物 | 4,756,985 bytes（约 4.54 MiB），SHA-256 `3F3AAC97B55AAC57F5048CAEA509A6A4D97620DC2FA6F195FF9F5BB531A32792` |
| 荣耀真机安装/启动烟测 | 通过：AAP-AN00、Android 16、Android System WebView 138.0.7204.179、1272×2800；USB 安装后可启动并显示演示首页 |

Windows 端对该荣耀设备需要设置 `ADB_LIBUSB=1` 才能稳定枚举；这只是本机连接兼容性记录，不是运行时功能依赖。当前尚未完成升级、后台恢复、断网/恢复、系统权限、TalkBack、TTS、触觉、320/375px 小屏和 PWA/APK/API 回滚演练，因此本记录不能单独批准 #234。
