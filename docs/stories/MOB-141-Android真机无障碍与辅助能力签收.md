# MOB-141 Android 真机无障碍与辅助能力签收

## 基本信息

| 字段 | 内容 |
| --- | --- |
| Issue | #228 |
| 状态 | 待 Android 真机验收 |
| 负责人 | ry12-20 |
| 计划工期 | 1 个工作日（真机可用后执行） |
| 关联 | #161、#164、#175、#176、#177、#178 |

## 需求

为既有移动端无障碍和辅助能力建立可复核的 Android 真机签收流程。代码、浏览器和模拟器检查只能证明部分实现，不能证明 TalkBack、中文 TTS、系统字号、触觉、系统拨号确认和 WebView 行为可用。

## 范围

- 提供九页真机路径、TalkBack 焦点、动态状态、错误/加载、对话框、字号、窄屏、TTS、触觉、高对比、减少动效与拨号的验收矩阵。
- 要求记录设备、Android/WebView/TalkBack/TTS 版本、系统设置、APK SHA-256、每条结果和脱敏证据。
- 增加 Node 证据门禁，拒绝把空模板、未执行项、模拟器或浏览器结果当作“通过”。

## 非目标

- 不新增业务 API、诊断、处方、药品建议或真实健康数据。
- 不把本环境的构建、单元测试或 `android:sync` 伪装成真机签收。
- 未连接设备时，不填写设备信息、APK 哈希、截图或通过结论。

## Given / When / Then

- Given 同一 APK 已安装在 Android 真机，When 依次完成九页 TalkBack 检查，Then 标题、焦点顺序、动态状态、对话框、错误和加载提示均可理解。
- Given 标准/大/特大字号以及 320/375px 窄屏，When 操作任务、识别、风险和求助，Then 没有截断、重叠、横向滚动或不足触控目标。
- Given TTS 不可用或首次交互受限，When 启用长辈模式或手动播报，Then 静默降级，文字操作和核心流程仍可用。
- Given 支持或不支持振动，When 任务完成、风险操作或确认拨号，Then 触觉反馈按约定出现或安全静默降级。
- Given 高对比与减少动效开启，When 浏览状态与交互，Then 文字、图标、边框和焦点可辨，动画停止。
- Given 点击急救或家人拨号，When 确认或取消，Then 号码、离开应用提示和焦点恢复正确。

## 测试与签收

执行 `npm run check`、`npm run test`、`npm run build`、`npm run android:sync` 后，按 [MOB-141 验收记录](../testing/MOB-141-Android真机无障碍验收记录.md) 在真机填写 12 个用例。所有条目通过并附脱敏证据后，执行：

```powershell
node APP/scripts/verify-android-a11y-evidence.mjs docs/testing/MOB-141-Android真机无障碍验收记录.md
```

当前没有连接可验收的 Android 真机，因此本 Story 保持待验收。

## 回滚

回退本 Story 的模板/门禁提交不会改变应用业务数据。发现真机缺陷时，建立独立 P0/P1/P2 Issue；修复回滚只回退对应修复，不移除既有 TalkBack、TTS、触觉或减少动效降级逻辑。
