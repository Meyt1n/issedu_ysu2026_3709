# APP启动优化与性能监控详解

> 本文档是家健镜系统 APP 启动优化与性能监控的完整设计说明，覆盖启动流程、冷启动优化、热启动优化、性能监控、ANR 防护。

## 1. 概述

### 1.1 优化目标

1. 冷启动时间 < 1.5 秒
2. 热启动时间 < 0.5 秒
3. 首屏渲染 < 1 秒
4. 卡顿率 < 0.1%
5. ANR 率 < 0.01%

### 1.2 启动阶段

| 阶段 | 说明 | 耗时目标 |
| --- | --- | --- |
| 进程创建 | 系统创建应用进程 | < 200ms |
| Application 初始化 | Application.onCreate | < 300ms |
| Activity 创建 | MainActivity 创建 | < 200ms |
| 首屏渲染 | 首帧绘制 | < 500ms |
| 数据加载 | 首屏数据加载 | < 300ms |

## 2. 启动流程

### 2.1 冷启动流程

```
用户点击图标
    ↓
系统创建进程（Zygote fork）
    ↓
Application.onCreate()
    ↓
MainActivity.onCreate()
    ↓
setContentView() / 渲染首屏
    ↓
onResume()
    ↓
首帧绘制完成
    ↓
数据加载完成
```

### 2.2 启动任务编排

```dart
class AppInitializer {
  Future<void> init() async {
    // 必须在主线程同步执行的任务
    await _initCritical();

    // 可以异步执行的任务
    _initAsync();

    // 延迟执行的任务
    _scheduleDelayed();
  }

  Future<void> _initCritical() async {
    // 崩溃监控（必须最先初始化）
    await CrashReporter.instance.init();

    // 路由配置
    AppRouter.configure();

    // 主题配置
    await ThemeManager.instance.load();
  }

  void _initAsync() {
    // 网络配置
    NetworkConfig.init();

    // 数据库初始化
    DatabaseHelper.instance.init();

    // 推送服务
    PushService.instance.init();
  }

  void _scheduleDelayed() {
    Future.delayed(Duration(seconds: 2), () {
      // 埋点 SDK
      AnalyticsService.instance.init();

      // 更新检查
      UpdateChecker.instance.check();
    });
  }
}
```

## 3. 冷启动优化

### 3.1 主题优化

```xml
<!-- 启动主题，避免白屏 -->
<style name="SplashTheme" parent="Theme.AppCompat.Light.NoActionBar">
    <item name="android:windowBackground">@drawable/splash_background</item>
    <item name="android:windowFullscreen">true</item>
</style>
```

### 3.2 懒加载

```dart
class LazyInitializer<T> {
  T? _instance;
  final T Function() _creator;

  LazyInitializer(this._creator);

  T get instance {
    _instance ??= _creator();
    return _instance!;
  }
}

// 使用
final databaseHelper = LazyInitializer(() => DatabaseHelper());
```

### 3.3 异步初始化

```dart
class AsyncInitWidget extends StatefulWidget {
  final Future<void> Function() init;
  final Widget child;
  final Widget? loading;

  AsyncInitWidget({required this.init, required this.child, this.loading});

  @override
  _AsyncInitWidgetState createState() => _AsyncInitWidgetState();
}

class _AsyncInitWidgetState extends State<AsyncInitWidget> {
  bool _initialized = false;

  @override
  void initState() {
    super.initState();
    widget.init().then((_) {
      if (mounted) setState(() => _initialized = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!_initialized) {
      return widget.loading ?? Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return widget.child;
  }
}
```

## 4. 热启动优化

### 4.1 进程保活

```dart
class ProcessKeeper {
  // 避免进程被回收
  static void keepAlive() {
    // 前台服务
    // 1像素 Activity
    // 账号同步
  }
}
```

### 4.2 状态保存

```dart
class MainActivity extends StatefulWidget {
  @override
  _MainActivityState createState() => _MainActivityState();
}

class _MainActivityState extends State<MainActivity> with RestorationMixin {
  final RestorableInt _currentIndex = RestorableInt(0);

  @override
  String? get restorationId => 'main_activity';

  @override
  void restoreState(RestorationBucket? oldBucket, bool initialRestore) {
    registerForRestoration(_currentIndex, 'current_index');
  }

  @override
  void dispose() {
    _currentIndex.dispose();
    super.dispose();
  }
}
```

## 5. 性能监控

### 5.1 启动时间监控

```dart
class StartupMetrics {
  static DateTime? _startTime;
  static DateTime? _firstFrameTime;
  static DateTime? _dataLoadedTime;

  static void onAppStart() {
    _startTime = DateTime.now();
  }

  static void onFirstFrame() {
    _firstFrameTime = DateTime.now();
    _reportColdStart();
  }

  static void onDataLoaded() {
    _dataLoadedTime = DateTime.now();
    _reportDataLoad();
  }

  static void _reportColdStart() {
    if (_startTime != null && _firstFrameTime != null) {
      final duration = _firstFrameTime!.difference(_startTime!).inMilliseconds;
      AnalyticsService.instance.logEvent(
        'cold_start_duration',
        parameters: {'duration_ms': duration},
      );
    }
  }
}
```

### 5.2 帧率监控

```dart
class FPSMonitor {
  static const int _windowSize = 100;
  final List<int> _frameTimes = [];
  int _lastFrameTime = 0;

  void onFrame(Duration timestamp) {
    final currentTime = timestamp.inMilliseconds;
    if (_lastFrameTime > 0) {
      final frameTime = currentTime - _lastFrameTime;
      _frameTimes.add(frameTime);
      if (_frameTimes.length > _windowSize) {
        _frameTimes.removeAt(0);
      }
    }
    _lastFrameTime = currentTime;
  }

  double get fps {
    if (_frameTimes.isEmpty) return 60.0;
    final avgFrameTime = _frameTimes.reduce((a, b) => a + b) / _frameTimes.length;
    return 1000 / avgFrameTime;
  }

  double get jankRate {
    if (_frameTimes.isEmpty) return 0.0;
    final jankFrames = _frameTimes.where((t) => t > 16.7).length;
    return jankFrames / _frameTimes.length;
  }
}
```

### 5.3 内存监控

```dart
class MemoryMonitor {
  void startMonitoring() {
    Timer.periodic(Duration(seconds: 30), (_) {
      _checkMemory();
    });
  }

  void _checkMemory() {
    // 获取内存使用情况
    final memoryInfo = _getMemoryInfo();

    // 内存过高告警
    if (memoryInfo.usedPercent > 85) {
      _triggerMemoryWarning();
    }

    // 上报内存指标
    AnalyticsService.instance.logEvent(
      'memory_usage',
      parameters: {
        'used_mb': memoryInfo.usedMB,
        'total_mb': memoryInfo.totalMB,
        'percent': memoryInfo.usedPercent,
      },
    );
  }

  void _triggerMemoryWarning() {
    // 清理缓存
    CacheManager.instance.clearMemoryCache();

    // 上报告警
    CrashReporter.instance.log('Memory warning: ${_getMemoryInfo()}');
  }
}
```

## 6. ANR 防护

### 6.1 主线程阻塞检测

```dart
class ANRDetector {
  static const int _threshold = 5000; // 5秒
  Timer? _timer;
  int _lastTick = 0;

  void start() {
    _timer = Timer.periodic(Duration(seconds: 1), (_) {
      _tick();
    });
  }

  void _tick() {
    final now = DateTime.now().millisecondsSinceEpoch;
    if (_lastTick > 0) {
      final delay = now - _lastTick - 1000;
      if (delay > _threshold) {
        _reportANR(delay);
      }
    }
    _lastTick = now;
  }

  void _reportANR(int delay) {
    final stackTrace = _getMainThreadStackTrace();
    CrashReporter.instance.reportANR(delay, stackTrace);
  }

  String _getMainThreadStackTrace() {
    // 获取主线程堆栈
    return StackTrace.current.toString();
  }

  void stop() {
    _timer?.cancel();
  }
}
```

### 6.2 耗时操作检测

```dart
class LongTaskDetector {
  static const int _threshold = 100; // 100ms

  static T run<T>(String name, T Function() task) {
    final startTime = DateTime.now().millisecondsSinceEpoch;
    final result = task();
    final duration = DateTime.now().millisecondsSinceEpoch - startTime;

    if (duration > _threshold) {
      AnalyticsService.instance.logEvent(
        'long_task',
        parameters: {
          'name': name,
          'duration_ms': duration,
        },
      );
    }

    return result;
  }
}
```

## 7. 包体积优化

### 7.1 资源优化

```yaml
# 构建配置
flutter:
  build:
    split-debug-info: true
    obfuscate: true
```

### 7.2 图片优化

- 使用 WebP 格式
- 压缩图片质量
- 使用矢量图
- 按需加载图片

## 8. 启动优化检查清单

- [ ] 冷启动时间
- [ ] 热启动时间
- [ ] 首屏渲染
- [ ] Application 初始化
- [ ] 懒加载
- [ ] 异步初始化
- [ ] 启动主题
- [ ] 帧率监控
- [ ] 内存监控
- [ ] ANR 防护
- [ ] 耗时检测
- [ ] 包体积优化

---

*快速的启动是用户体验的第一印象。精准的监控，持续的优化，让 APP 启动如闪电般迅速。*
