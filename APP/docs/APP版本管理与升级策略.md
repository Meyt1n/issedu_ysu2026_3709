# APP版本管理与升级策略

> 本文档是家健镜系统 APP 版本管理与升级策略的完整设计说明，覆盖版本号规范、发布流程、灰度发布、强制更新、回滚策略。

## 1. 概述

### 1.1 设计目标

1. 版本号清晰可追溯
2. 发布流程标准化
3. 灰度发布降低风险
4. 关键更新可强制
5. 问题可快速回滚

### 1.2 版本类型

| 类型 | 说明 | 发布频率 |
| --- | --- | --- |
| 主版本 | 重大功能更新 | 3-6 个月 |
| 次版本 | 新功能、优化 | 2-4 周 |
| 修订版本 | Bug 修复 | 按需 |
| 热修复 | 紧急修复 | 按需 |

## 2. 版本号规范

### 2.1 语义化版本

```
主版本号.次版本号.修订版本号+构建号

示例：
1.2.3+45
│ │ │  └─ 构建号（每次构建递增）
│ │ └──── 修订版本（Bug 修复）
│ └────── 次版本（新功能）
└──────── 主版本（重大更新）
```

### 2.2 版本号规则

```python
class Version:
    def __init__(self, major: int, minor: int, patch: int, build: int = 0):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.build = build

    def __str__(self):
        return f"{self.major}.{self.minor}.{self.patch}+{self.build}"

    def increment_major(self):
        return Version(self.major + 1, 0, 0)

    def increment_minor(self):
        return Version(self.major, self.minor + 1, 0)

    def increment_patch(self):
        return Version(self.major, self.minor, self.patch + 1)

    def compare(self, other: "Version") -> int:
        if self.major != other.major:
            return self.major - other.major
        if self.minor != other.minor:
            return self.minor - other.minor
        if self.patch != other.patch:
            return self.patch - other.patch
        return self.build - other.build
```

### 2.3 版本命名

```
# 开发版本
1.3.0-alpha.1
1.3.0-beta.2
1.3.0-rc.1

# 正式版本
1.3.0

# 热修复
1.3.1
```

## 3. 发布流程

### 3.1 发布阶段

```
开发完成 → 测试验证 → 预发布 → 灰度发布 → 全量发布
    ↓          ↓          ↓          ↓          ↓
  功能冻结   回归测试   生产验证   10%用户    100%用户
```

### 3.2 发布检查清单

```python
class ReleaseChecklist:
    def __init__(self):
        self.items = [
            ("功能测试", "所有新功能测试通过"),
            ("回归测试", "核心功能回归测试通过"),
            ("性能测试", "性能指标达标"),
            ("安全测试", "安全扫描无高危漏洞"),
            ("兼容性", "支持的设备和系统版本测试"),
            ("升级测试", "从旧版本升级测试"),
            ("回滚方案", "回滚方案已准备"),
            ("发布说明", "更新日志已编写"),
            ("监控配置", "监控和告警已配置"),
        ]

    def check(self) -> dict:
        return {
            "ready": all(item[1] for item in self.items),
            "items": [{"name": name, "description": desc} for name, desc in self.items],
        }
```

## 4. 灰度发布

### 4.1 灰度策略

```python
class GrayReleaseManager:
    def __init__(self):
        self.stages = [
            {"percentage": 1, "duration": 24, "name": "内部测试"},
            {"percentage": 5, "duration": 24, "name": "小范围灰度"},
            {"percentage": 20, "duration": 24, "name": "中范围灰度"},
            {"percentage": 50, "duration": 24, "name": "大范围灰度"},
            {"percentage": 100, "duration": 0, "name": "全量发布"},
        ]

    def should_update(self, user_id: str, current_stage: int) -> bool:
        stage = self.stages[current_stage]
        hash_value = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 100
        return hash_value < stage["percentage"]

    def next_stage(self, current_stage: int, metrics: dict) -> int:
        # 检查指标是否达标
        if metrics["crash_rate"] < 0.1 and metrics["error_rate"] < 1:
            return min(current_stage + 1, len(self.stages) - 1)
        return current_stage  # 暂停灰度
```

### 4.2 灰度配置

```json
{
  "version": "1.3.0",
  "stages": [
    {
      "stage": 1,
      "percentage": 1,
      "start_time": "2026-09-01T10:00:00Z",
      "criteria": {
        "max_crash_rate": 0.5,
        "max_error_rate": 2,
        "min_duration_hours": 24
      }
    },
    {
      "stage": 2,
      "percentage": 10,
      "criteria": {
        "max_crash_rate": 0.3,
        "max_error_rate": 1.5,
        "min_duration_hours": 24
      }
    }
  ]
}
```

## 5. 强制更新

### 5.1 强制更新判断

```dart
class UpdateManager {
  Future<UpdateInfo> checkUpdate() async {
    final currentVersion = await _getCurrentVersion();
    final latestVersion = await _api.getLatestVersion();

    return UpdateInfo(
      currentVersion: currentVersion,
      latestVersion: latestVersion.version,
      updateUrl: latestVersion.downloadUrl,
      forceUpdate: _shouldForceUpdate(currentVersion, latestVersion),
      releaseNotes: latestVersion.releaseNotes,
    );
  }

  bool _shouldForceUpdate(String current, LatestVersion latest) {
    // 主版本不兼容
    if (latest.minSupportedVersion != null) {
      return _compareVersions(current, latest.minSupportedVersion!) < 0;
    }

    // 配置了强制更新版本
    return latest.forceUpdateVersions.contains(current);
  }
}
```

### 5.2 更新弹窗

```dart
class UpdateDialog extends StatelessWidget {
  final UpdateInfo updateInfo;

  @override
  Widget build(BuildContext context) {
    if (updateInfo.forceUpdate) {
      // 强制更新：不可关闭
      return AlertDialog(
        title: Text('发现重要更新'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('当前版本需要更新才能继续使用'),
            SizedBox(height: 16),
            Text(updateInfo.releaseNotes),
          ],
        ),
        actions: [
          ElevatedButton(
            onPressed: () => _downloadUpdate(updateInfo.updateUrl),
            child: Text('立即更新'),
          ),
        ],
        barrierDismissible: false,
      );
    }

    // 普通更新：可关闭
    return AlertDialog(
      title: Text('发现新版本'),
      content: Text(updateInfo.releaseNotes),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text('稍后')),
        ElevatedButton(
          onPressed: () => _downloadUpdate(updateInfo.updateUrl),
          child: Text('立即更新'),
        ),
      ],
    );
  }
}
```

## 6. 热修复

### 6.1 热修复方案

```dart
// 方案1：资源热修复（配置、文案、图片）
class HotFixManager {
  Future<void> checkAndApplyHotFix() async {
    final hotFix = await _api.getLatestHotFix();

    if (hotFix != null && hotFix.version == currentVersion) {
      await _downloadHotFix(hotFix);
      await _applyHotFix(hotFix);
    }
  }

  Future<void> _applyHotFix(HotFix hotFix) async {
    // 应用配置热修复
    if (hotFix.configPatch != null) {
      await _configManager.applyPatch(hotFix.configPatch);
    }

    // 应用文案热修复
    if (hotFix.stringPatch != null) {
      await _stringManager.applyPatch(hotFix.stringPatch);
    }
  }
}
```

### 6.2 动态化方案

```dart
// 方案2：动态化（如 Flutter Fair、MXFlutter）
class DynamicPage extends StatelessWidget {
  final String pageId;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<DynamicWidget>(
      future: _dynamicLoader.load(pageId),
      builder: (context, snapshot) {
        if (snapshot.hasData) {
          return snapshot.data!.build(context);
        }
        return _fallbackPage();
      },
    );
  }
}
```

## 7. 回滚策略

### 7.1 回滚触发条件

```python
class RollbackTrigger:
    def __init__(self):
        self.thresholds = {
            "crash_rate": 0.5,      # 崩溃率 > 0.5%
            "error_rate": 2.0,      # 错误率 > 2%
            "rating_drop": 0.3,     # 评分下降 > 0.3
            "support_tickets": 50,  # 客服工单 > 50/天
        }

    def should_rollback(self, metrics: dict) -> tuple[bool, str]:
        for metric, threshold in self.thresholds.items():
            if metrics.get(metric, 0) > threshold:
                return True, f"{metric} 超过阈值 {threshold}"
        return False, ""
```

### 7.2 回滚执行

```python
class RollbackManager:
    def __init__(self, app_store_api):
        self.api = app_store_api

    def rollback(self, version: str):
        # 1. 停止灰度
        self._stop_gray_release()

        # 2. 回退到上一版本
        self.api.promote_version(version)

        # 3. 通知用户
        self._notify_users()

        # 4. 记录回滚原因
        self._record_rollback(version)
```

## 8. 版本管理检查清单

- [ ] 版本号规范
- [ ] 发布流程
- [ ] 发布检查清单
- [ ] 灰度发布
- [ ] 灰度配置
- [ ] 强制更新
- [ ] 更新弹窗
- [ ] 热修复
- [ ] 动态化
- [ ] 回滚触发
- [ ] 回滚执行
- [ ] 版本监控

---

*版本管理是质量的最后一道防线。规范的流程、稳健的灰度、快速的回滚，让每次发布都安心。*
