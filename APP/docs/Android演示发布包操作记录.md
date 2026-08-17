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

## 本机验证记录（2026-08-17）

| 检查 | 结果 |
| --- | --- |
| `npm run check` | 通过 |
| `npm run test` | 通过，43 tests passed |
| `npm run build` | 通过 |
| `npm run android:sync` | 通过 |
| `scripts/build-apk.ps1` | 阻塞：未发现 `C:\Users\C\AppData\Local\Android\Sdk`，未生成 APK |

本机 `JAVA_HOME` 已设置，但 Android SDK 未安装或未配置。安装 Android Studio SDK 后，设置 `ANDROID_HOME` 到实际 SDK 目录并重跑构建脚本。此记录不构成真机安装或 APK 发布验证。
