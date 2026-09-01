# MOB-171 Android/PWA 受控局部验收记录（2026-09-01）

> 本记录只覆盖当前候选提交上的受控局部复核，不替代维护者的完整发布签收。使用的家庭、成员、任务和风险均由 `APP/scripts/mob171-weak-network-fixture.mjs` 即时生成，不含真实健康数据。

## 环境与边界

| 字段 | 记录 |
| --- | --- |
| 候选提交 | 本分支基于 `origin/master` 的 MOB-171 修复候选 |
| Android 设备 | 荣耀 AAP-AN00，Android 16，Android System WebView 138.0.7204.179 |
| APK | Debug 构建（`android-debug`），SHA-256：`9EDB9EEFA6A6697618EB22CD084631D2E46570FFCD7D4908ECC1CB7CABA98E3D` |
| PWA | Chromium 151.0.7922.34，390×844；窄屏复核 320×844 |
| API/数据 | `mob171-weak-network-fixture.mjs`，MOB-171 synthetic v1；私有局域网临时地址，不记录具体地址 |
| 身份/成员 | `mob171-synthetic`、`MOB-171 合成家庭`、`成员A（合成）` |
| 场景 | `loading`、`timeout`、`slow`/504、`empty`、`partial`；`partial` 仅让 `weekly-trend` 失败 |
| 辅助设置 | Android/PWA 减少动效；PWA 窄屏；真机请求状态通过 WebView CDP 读取 |

## 复核结果

| 用例 | 结果 | 可定位事实 |
| --- | --- | --- |
| MOB171-NET-01 Android 首次加载 | 通过 | 3 个骨架卡、`role=status`、`aria-busy=true`；未显示合成任务内容 |
| MOB171-NET-02 PWA 首次加载 | 通过 | 3 个骨架卡、加载播报“正在加载家庭和成员数据…”；未误报为空 |
| MOB171-NET-03 Android + PWA 减少动效 | 通过 | 根节点 `data-motion=reduced`；骨架伪元素 `display:none`，无扫光动画 |
| MOB171-NET-04 Android 连接超时 | 通过 | 15 秒客户端超时后显示“连接等待超时”，请求 ID 缺失时如实提示并保留重试入口 |
| MOB171-NET-05 PWA 服务端慢/504 | 通过 | 显示“服务端处理较慢”，携带合成请求标识；与连接超时文案不同 |
| MOB171-NET-06 Android + PWA 空集合 | 通过 | 家庭成员页显示“确实没有可用的家庭成员”，不显示骨架或错误卡 |
| MOB171-NET-07 Android 部分数据失败 | 通过 | 合成 `weekly-trend` 返回 504，今日任务/风险仍显示，警示卡提供“重试补齐” |
| MOB171-NET-08 PWA 连续点击重试 | 通过 | 点击后保留错误卡，按钮变为 disabled/“正在重试…”；夹具只收到 1 次成员请求 |
| MOB171-NET-09 Android + PWA 断网→恢复 | 待维护者签收 | 本次完成受控错误→`ok` 回切烟测，尚未模拟系统级断网和恢复后的完整播报顺序 |
| MOB171-NET-10 Android TalkBack | 待维护者签收 | 代码提供 `role=status`/`aria-live`，但本次未以设备持有人身份完成 TalkBack 逐次播报签收 |
| MOB171-NET-11 PWA 窄屏/特大字号错误态 | 通过（窄屏） | 320px 视口无横向溢出，错误原因、请求标识和重试动作均可见；特大字号仍需设备持有人复核 |
| MOB171-NET-12 Android + PWA 隐私/占位 | 通过 | 证据仅含合成别名和本地夹具提示；未写入真实身份、健康正文、token 或公网地址 |

## 证据附件

以下截图均为合成数据；哈希用于复核文件未被替换。Android 截图来自安装包复核，PWA 截图来自同一夹具的 Chromium 复核。

| 端 | 场景 | 相对路径 | SHA-256 |
| --- | --- | --- | --- |
| Android | 骨架加载 | `MOB-171-android-loading.png` | `0BBD7868CDF5DE46AB2F6CB7C4E2054DF125CA6A1A547EE0DE707656A688D9C6` |
| Android | 服务端慢 | `MOB-171-android-slow-fresh.png` | `0CEE9A45CF2F6489C689278F2DBE59D1571D053CCB4091EC82C8E6A29BCCB288` |
| Android | 部分数据 | `MOB-171-android-partial-fresh.png` | `AA70F3055E8874CC517E872C2AE8491884BBACABF0AF87806EDA4E475E413002` |
| Android | 减少动效 | `MOB-171-android-reduced-motion-fresh.png` | `1FA88669A5344F74A4CDA863B8291F9E2C788B70AEE2A4AF5EDCC0F7EBBAC540` |
| Android | 空集合 | `MOB-171-android-empty-fresh.png` | `ADB2DD853C8F3DB2A0CC8F8E51ADFB7CBC1CA46D6B44B6F796C1C8447404CBD5` |
| Android | 连接超时 | `MOB-171-android-timeout-fresh.png` | `991D3A5AB9578435E794FD47208CBD101FC7DDAF3E811C4F77FC74FCA7EB3DAA` |
| PWA | 骨架加载 | `MOB-171-pwa-loading-final.png` | `EF3B172C5416FCB1FAE3B3A6AA364C8406A3C115DDB9C6403B294EB6F1B6B380` |
| PWA | 服务端慢 | `MOB-171-pwa-slow-final2.png` | `31A8048F256D2AAB23E3DDA7C92C9A9D575AC3FD21BD46DDC1644C64AD6D74BA` |
| PWA | 部分数据 | `MOB-171-pwa-partial-final3.png` | `0F144825CAA335E4AAB569F079F2701F18A23C7E47C481D6B055F805F6B5552E` |
| PWA | 减少动效 | `MOB-171-pwa-reduced-motion-final.png` | `1D16FD385EB622DE10BC9ACC8E97236920AFFE81FBE469B03960A79416B42E07` |
| PWA | 重试锁定 | `MOB-171-pwa-retry-lock-final.png` | `2F9E30F41666A0B7704FBDDB636F7A6164DA47596128FDB58B997D5AA64157DF` |
| PWA | 窄屏 | `MOB-171-pwa-narrow-xlarge-final.png` | `F2340F59909FF7D741DDEE9F82FF34EC31C7469D8EE6F3800CAAC6859262E699` |

## 自动检查

- `npm run check`：通过。
- `npm run test -- --reporter=dot`：39 个测试文件、356 项通过。
- `npm run audit:android-security`：通过；Release 仍禁止明文 HTTP，Debug 受控局域网链路才允许。
- `npm exec vite build -- --mode android-debug`：通过。
- `APP/android/gradlew.bat assembleDebug --no-daemon --console=plain`：通过；Kotlin daemon 在受限目录失败后使用 Gradle fallback，不影响构建结果。
- `git diff --check`：通过。

## 后续签收

维护者仍需在最终候选上完成系统级断网→恢复、TalkBack 逐次播报、特大字号以及完整附件哈希回填；在这些事实源完成前，MOB-171 保持“待验收”，不能作为移动端发布通过证明。
