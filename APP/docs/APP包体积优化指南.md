# APP包体积优化指南

> 本文档是家健镜系统 APP 包体积优化的完整指南，覆盖资源优化、代码优化、依赖优化、构建优化。

## 1. 包体积概述

### 1.1 优化目标

1. 减小安装包大小
2. 加快下载速度
3. 减少存储空间占用
4. 提升用户体验
5. 降低流量成本

### 1.2 体积构成

| 组成部分 | 占比 | 优化空间 |
| --- | --- | --- |
| 代码 | 30% | 中 |
| 资源（图片/字体） | 40% | 大 |
| 第三方 SDK | 20% | 中 |
| 其他 | 10% | 小 |

## 2. 资源优化

### 2.1 图片优化

```yaml
# pubspec.yaml
flutter:
  assets:
    - assets/images/
    # 使用 WebP 格式代替 PNG
```

```bash
# 使用 cwebp 转换图片
cwebp -q 80 image.png -o image.webp

# 使用 pngquant 压缩 PNG
pngquant --quality=65-80 image.png

# 使用 SVG 矢量图
# 适合图标和简单图形
```

### 2.2 图片懒加载

```dart
class LazyImage extends StatelessWidget {
  final String url;

  LazyImage({required this.url});

  @override
  Widget build(BuildContext context) {
    return Image.network(
      url,
      cacheWidth: 300,  // 缓存时缩放
      loadingBuilder: (context, child, progress) {
        if (progress == null) return child;
        return CircularProgressIndicator();
      },
      errorBuilder: (context, error, stackTrace) {
        return Icon(Icons.broken_image);
      },
    );
  }
}
```

### 2.3 字体优化

```yaml
# pubspec.yaml
flutter:
  fonts:
    - family: CustomFont
      fonts:
        - asset: fonts/CustomFont-Regular.ttf
          weight: 400
        # 只包含需要的字重
```

```bash
# 使用 fonttools 子集化字体
pyftsubset font.ttf --text="常用汉字列表" --output-file=font_subset.ttf
```

### 2.4 资源分包

```dart
// 延迟加载资源
Future<void> loadAssets() async {
  // 只在需要时加载
  final image = await rootBundle.load('assets/large_image.webp');
}
```

## 3. 代码优化

### 3.1 代码混淆

```yaml
# android/app/build.gradle
android {
    buildTypes {
        release {
            minifyEnabled true
            shrinkResources true
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'),
                         'proguard-rules.pro'
        }
    }
}
```

### 3.2 Tree Shaking

Flutter 构建时自动进行 Tree Shaking，移除未使用的代码。

```dart
// 避免使用 dart:mirrors（会阻止 Tree Shaking）
// 避免动态导入
```

### 3.3 延迟加载

```dart
// 使用 deferred import 延迟加载库
import 'package:heavy_library/heavy_library.dart' deferred as heavy;

Future<void> useHeavyLibrary() async {
  await heavy.loadLibrary();
  heavy.doSomething();
}
```

## 4. 依赖优化

### 4.1 依赖审计

```bash
# 查看依赖树
flutter pub deps

# 检查过时依赖
flutter pub outdated
```

### 4.2 移除未使用依赖

```yaml
# pubspec.yaml
dependencies:
  flutter:
    sdk: flutter
  # 只保留实际使用的依赖
  http: ^1.0.0
  # 移除未使用的依赖
```

### 4.3 替代重型依赖

| 重型依赖 | 轻量替代 |
| --- | --- |
| firebase_analytics | 自建统计 |
| google_maps_flutter | 高德/百度地图 |
| video_player | 按需加载 |

## 5. 构建优化

### 5.1 拆分 ABI

```gradle
// android/app/build.gradle
android {
    splits {
        abi {
            enable true
            reset()
            include 'armeabi-v7a', 'arm64-v8a', 'x86_64'
            universalApk false
        }
    }
}
```

### 5.2 App Bundle

```bash
# 构建 AAB（Android App Bundle）
flutter build appbundle --release

# AAB 会根据设备自动分发所需资源
```

### 5.3 iOS 优化

```bash
# 构建 IPA
flutter build ipa --release

# 开启 Bitcode（Xcode 14 已废弃）
# 优化编译选项
```

## 6. 动态功能模块

### 6.1 Android Dynamic Feature

```gradle
// 动态功能模块
android {
    dynamicFeatures = [':feature_chat', ':feature_vision']
}
```

### 6.2 按需下载

```dart
// 使用 Play Core 按需下载功能模块
class FeatureManager {
  static Future<void> installFeature(String moduleName) async {
    // 下载并安装功能模块
  }
}
```

## 7. 体积监控

### 7.1 体积分析

```bash
# 分析 APK 体积
flutter build apk --release --analyze-size

# 查看详细报告
# 输出到 build/app/outputs/apk/release/
```

### 7.2 CI 监控

```yaml
- name: Check APK size
  run: |
    APK_SIZE=$(stat -c%s build/app/outputs/apk/release/app-release.apk)
    if [ $APK_SIZE -gt 52428800 ]; then
      echo "APK size exceeds 50MB"
      exit 1
    fi
```

## 8. 包体积优化检查清单

- [ ] 图片压缩（WebP）
- [ ] 图片懒加载
- [ ] 字体子集化
- [ ] 资源分包
- [ ] 代码混淆
- [ ] Tree Shaking
- [ ] 延迟加载
- [ ] 移除未使用依赖
- [ ] 替代重型依赖
- [ ] ABI 拆分
- [ ] App Bundle
- [ ] 动态功能模块
- [ ] 体积监控
- [ ] CI 体积检查

---

*包体积优化是用户体验的细节。每减少 1MB，都能让更多用户顺利下载安装。*
