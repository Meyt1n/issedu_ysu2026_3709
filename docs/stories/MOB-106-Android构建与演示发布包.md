# MOB-106：Android 构建与演示发布包

- 需求：NFR-04、NFR-06、NFR-07
- Issue：[ #164 ](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/164)
- 状态：进行中
- 负责人：ry12-20
- 风险：R2。构建产物、局域网服务地址或联机能力若未实际验证，不得声明为可发布能力。
- 允许修改目录：`APP/scripts/`、`APP/docs/`、`APP/README.md`、`docs/stories/`

## 用户价值
作为演示人员，我需要可重复构建的 Android 调试 APK，以及清楚的安装、局域网联机、已知限制和回滚步骤，才能在不混入真实数据的前提下演示移动端。

## 范围
- 验证 Web 类型检查、测试、生产构建与 Capacitor Android 同步。
- 记录本机构建环境、APK 路径、安装和局域网联机步骤。
- 对 SDK、JDK 或 Gradle 依赖缺失如实记录阻塞，不伪造产物。

## 非目标
不发布到应用商店；不引入真实服务地址、真实家庭数据、签名密钥或正式生产鉴权；不宣称真机可用，除非实际完成安装验证。

## Given / When / Then
- 正常：Given 已安装兼容 JDK、Android SDK 和锁定 npm 依赖，When 运行构建脚本，Then 生成 `android/app/build/outputs/apk/debug/app-debug.apk`。
- 边界：Given 项目路径包含中文，When 同步 Android，Then 使用现有 `android.overridePathCheck=true` 配置继续或输出真实 Gradle 错误。
- 失败：Given SDK/JDK/Gradle 缺失，When 构建，Then 明确指出缺失依赖和修复命令，不声明 APK 已生成。
- 未授权：Given 未配置家庭服务端或身份，When 安装后切换联机模式，Then 显示连接/授权错误，不显示演示数据为联机数据。

## 测试
`cd APP && npm run check`；`npm run test`；`npm run build`；`npm run android:sync`；以及可用环境中的 `gradlew.bat assembleDebug`。

## 回滚
PR 未合并前关闭 PR；合并后 revert 本 PR。删除本机构建产物或 `android/local.properties` 不影响源码、服务端数据和已发布版本。
