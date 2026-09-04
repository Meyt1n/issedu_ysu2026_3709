# APP启动优化与性能监控

> 本文档是家健镜系统 APP 启动优化与性能监控的完整指南，覆盖启动流程、优化策略、性能监控、ANR 处理。

## 1. 启动优化概述

### 1.1 设计目标

1. 快速启动：冷启动 < 2 秒
2. 流畅体验：无卡顿、无白屏
3. 稳定运行：无 ANR、无崩溃
4. 可监控：性能数据可采集
5. 可优化：持续优化有依据

### 1.2 启动类型

| 类型 | 说明 | 目标时间 |
| --- | --- | --- |
| 冷启动 | 进程不存在，从头启动 | < 2s |
| 温启动 | 进程存在，Activity 重建 | < 1s |
| 热启动 | 进程和 Activity 都存在 | < 0.5s |

## 2. 启动流程

### 2.1 冷启动流程

```
Application.onCreate()
    ↓
初始化 SDK（推送、统计、地图...）
    ↓
创建 MainActivity
    ↓
加载布局
    ↓
初始化数据
    ↓
渲染首屏
    ↓
用户可交互
```

### 2.2 启动耗时分析

```dart
class LaunchTimer {
  static Map<String, int> _timestamps = {};

  static void start(String phase) {
    _timestamps[phase] = DateTime.now().millisecondsSinceEpoch;
  }

  static void end(String phase) {
    final start = _timestamps[phase];
    if (start != null) {
      final duration = DateTime.now().millisecondsSinceEpoch - start;
      debugPrint('$phase 耗时: ${duration}ms');
      AnalyticsManager().track('launch_performance', properties: {
        'phase': phase,
        'duration_ms': duration,
      });
    }
  }
}
```

## 3. 优化策略

### 3.1 异步初始化

```dart
// 错误：在 main 中同步初始化所有 SDK
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  PushService.init();      // 耗时 200ms
  AnalyticsService.init();  // 耗时 150ms
  MapService.init();        // 耗时 300ms
  runApp(MyApp());
}

// 正确：异步初始化，不阻塞启动
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(MyApp());

  // 后台异步初始化
  Future.delayed(Duration.zero, () {
    PushService.init();
    AnalyticsService.init();
    MapService.init();
  });
}
```

### 3.2 懒加载

```dart
// 错误：启动时加载所有数据
class HomePage extends StatefulWidget {
  @override
  _HomePageState createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  @override
  void initState() {
    super.initState();
    _loadAllData();  // 加载所有页面数据
  }
}

// 正确：按需加载
class HomePage extends StatefulWidget {
  @override
  _HomePageState createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  @override
  void initState() {
    super.initState();
    _loadHomeData();  // 只加载首页数据
  }
}

// 使用 LazyBuilder 延迟构建
class LazyPage extends StatelessWidget {
  final WidgetBuilder builder;
  LazyPage({required this.builder});

  @override
  Widget build(BuildContext context) {
    return Builder(builder: builder);
  }
}
```

### 3.3 首屏优化

```dart
// 使用 Skeleton 占位
class SkeletonLoader extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: Colors.grey[300]!,
      highlightColor: Colors.grey[100]!,
      child: Column(
        children: [
          Container(height: 20, width: 200, color: Colors.white),
          SizedBox(height: 10),
          Container(height: 20, width: 150, color: Colors.white),
        ],
      ),
    );
  }
}

// 缓存首屏数据
class HomeCache {
  static Map<String, dynamic>? _cachedData;

  static Future<void> preload() async {
    _cachedData = await ApiClient.get('/home/data');
  }

  static Map<String, dynamic>? get data => _cachedData;
}
```

### 3.4 图片优化

```dart
// 使用 cached_network_image
CachedNetworkImage(
  imageUrl: url,
  placeholder: (context, url) => CircularProgressIndicator(),
  errorWidget: (context, url, error) => Icon(Icons.error),
  memCacheWidth: 300,  // 内存缓存宽度
  maxWidthDiskCache: 300,  // 磁盘缓存宽度
);

// 预加载图片
precacheImage(NetworkImage(url), context);
```

### 3.5 代码优化

```dart
// 避免在 build 中做耗时操作
// 错误
@override
Widget build(BuildContext context) {
  final data = _parseData();  // 耗时操作
  return Text(data);
}

// 正确
@override
void initState() {
  super.initState();
  _data = _parseData();  // 在 initState 中计算
}

@override
Widget build(BuildContext context) {
  return Text(_data);
}

// 使用 const 构造函数
const Text('Hello');  // 避免重复构建
```

## 4. 性能监控

### 4.1 FPS 监控

```dart
class FPSMonitor {
  static int _frameCount = 0;
  static int _lastTime = 0;

  static void start() {
    WidgetsBinding.instance.addTimingsCallback((timings) {
      for (final timing in timings) {
        _frameCount++;
        final now = DateTime.now().millisecondsSinceEpoch;
        if (now - _lastTime >= 1000) {
          final fps = _frameCount * 1000 / (now - _lastTime);
          AnalyticsManager().track('fps', properties: {'fps': fps});
          _frameCount = 0;
          _lastTime = now;
        }
      }
    });
  }
}
```

### 4.2 内存监控

```dart
class MemoryMonitor {
  static void start() {
    Timer.periodic(Duration(minutes: 5), (_) {
      final info = ProcessInfo.currentRss;
      AnalyticsManager().track('memory_usage', properties: {
        'rss_mb': info / 1024 / 1024,
      });
    });
  }
}
```

### 4.3 页面耗时监控

```dart
class PerformanceRouteObserver extends RouteObserver<PageRoute> {
  Map<String, int> _pageEnterTimes = {};

  @override
  void didPush(Route route, Route? previousRoute) {
    super.didPush(route, previousRoute);
    final pageName = route.settings.name ?? 'unknown';
    _pageEnterTimes[pageName] = DateTime.now().millisecondsSinceEpoch;
  }

  @override
  void didPop(Route route, Route? previousRoute) {
    super.didPop(route, previousRoute);
    final pageName = route.settings.name ?? 'unknown';
    final enterTime = _pageEnterTimes.remove(pageName);
    if (enterTime != null) {
      final duration = DateTime.now().millisecondsSinceEpoch - enterTime;
      AnalyticsManager().track('page_duration', properties: {
        'page': pageName,
        'duration_ms': duration,
      });
    }
  }
}
```

## 5. ANR 处理

### 5.1 ANR 检测

```dart
class ANRDetector {
  static const _threshold = 5000; // 5 秒
  static Timer? _timer;
  static int _lastUiTime = 0;

  static void start() {
    _lastUiTime = DateTime.now().millisecondsSinceEpoch;

    // 主线程计时
    Timer.periodic(Duration(milliseconds: 100), (_) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _lastUiTime = DateTime.now().millisecondsSinceEpoch;
      });
    });

    // 检测线程
    _timer = Timer.periodic(Duration(seconds: 1), (_) {
      final now = DateTime.now().millisecondsSinceEpoch;
      if (now - _lastUiTime > _threshold) {
        AnalyticsManager().track('anr_detected', properties: {
          'blocked_ms': now - _lastUiTime,
        });
      }
    });
  }
}
```

### 5.2 避免 ANR

- 不在主线程做网络请求
- 不在主线程做数据库操作
- 不在主线程做大量计算
- 使用 compute 处理耗时计算

```dart
// 使用 compute 在后台线程处理
Future<List<int>> parseData(String data) async {
  return compute(_parseData, data);
}

List<int> _parseData(String data) {
  // 耗时计算
  return data.codeUnits;
}
```

## 6. 崩溃监控

### 6.1 全局异常捕获

```dart
void main() {
  FlutterError.onError = (FlutterErrorDetails details) {
    AnalyticsManager().track('flutter_error', properties: {
      'error': details.exception.toString(),
      'stack': details.stack.toString(),
    });
  };

  runZonedGuarded(() {
    runApp(MyApp());
  }, (error, stack) {
    AnalyticsManager().track('unhandled_error', properties: {
      'error': error.toString(),
      'stack': stack.toString(),
    });
  });
}
```

## 7. 性能优化检查清单

- [ ] 冷启动 < 2s
- [ ] 异步初始化
- [ ] 懒加载
- [ ] 首屏 Skeleton
- [ ] 图片缓存
- [ ] const 优化
- [ ] FPS 监控
- [ ] 内存监控
- [ ] 页面耗时监控
- [ ] ANR 检测
- [ ] 崩溃监控
- [ ] 性能告警

---

*性能是用户体验的基石。快速、流畅、稳定的 APP，让用户爱不释手。*
