# APP性能优化与启动加速

> 本文档是家健镜系统 APP 性能优化与启动加速的完整设计说明，覆盖启动优化、渲染优化、内存优化、网络优化、包体积优化。

## 1. 概述

### 1.1 性能目标

1. 冷启动 < 1.5 秒
2. 热启动 < 0.5 秒
3. 页面渲染 60fps
4. 内存峰值 < 200MB
5. 包体积 < 50MB

### 1.2 性能指标

| 指标 | 目标 | 测量方式 |
| --- | --- | --- |
| 冷启动时间 | < 1.5s | 从点击到首页可交互 |
| 热启动时间 | < 0.5s | 从后台到前台 |
| 页面切换 | < 300ms | 路由跳转耗时 |
| 列表滚动 | 60fps | 滚动帧率 |
| 内存占用 | < 200MB | 峰值内存 |
| 启动崩溃率 | < 0.1% | 启动阶段崩溃 |

## 2. 启动优化

### 2.1 启动流程

```
Application.onCreate()
    ↓
初始化 SDK（延迟非必要）
    ↓
MainActivity.onCreate()
    ↓
加载首屏布局
    ↓
初始化首屏数据（异步）
    ↓
首屏可交互
```

### 2.2 延迟初始化

```dart
void main() {
  // 1. 先启动 APP
  runApp(MyApp());

  // 2. 延迟初始化非必要 SDK
  Future.delayed(Duration(milliseconds: 500), () {
    initAnalytics();
    initCrashlytics();
    initPushService();
  });
}

// 使用时再初始化
class AnalyticsService {
  static AnalyticsService? _instance;
  static bool _initialized = false;

  static Future<AnalyticsService> get instance async {
    if (!_initialized) {
      await _init();
      _initialized = true;
    }
    return _instance!;
  }
}
```

### 2.3 预加载

```dart
class PreloadManager {
  static Future<void> preload() async {
    // 预加载常用数据
    await Future.wait([
      UserManager.instance.loadUser(),
      MedicineRepository.instance.cacheMedicines(),
      HealthDataService.instance.cacheTodayData(),
    ]);
  }
}

// 在启动页预加载
class SplashPage extends StatefulWidget {
  @override
  _SplashPageState createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  @override
  void initState() {
    super.initState();
    _initAndNavigate();
  }

  Future<void> _initAndNavigate() async {
    await PreloadManager.preload();
    Navigator.of(context).pushReplacementNamed('/home');
  }
}
```

### 2.4 启动页优化

```xml
<!-- Android: 使用 launch_background 减少白屏 -->
<!-- res/drawable/launch_background.xml -->
<?xml version="1.0" encoding="utf-8"?>
<layer-list xmlns:android="http://schemas.android.com/apk/res/android">
    <item android:drawable="@color/white" />
    <item>
        <bitmap
            android:gravity="center"
            android:src="@mipmap/ic_launcher" />
    </item>
</layer-list>
```

## 3. 渲染优化

### 3.1 Widget 优化

```dart
// 不好：每次 build 都创建新对象
class BadWidget extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      child: Text('Hello'),
    );
  }
}

// 好：使用 const 构造函数
class GoodWidget extends StatelessWidget {
  const GoodWidget({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Text('Hello'),
    );
  }
}
```

### 3.2 列表优化

```dart
class OptimizedListView extends StatelessWidget {
  final List<Medicine> medicines;

  OptimizedListView({required this.medicines});

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      itemCount: medicines.length,
      itemExtent: 80,  // 固定高度，避免反复计算
      cacheExtent: 500,  // 预缓存区域
      itemBuilder: (context, index) {
        return MedicineListItem(
          medicine: medicines[index],
          key: ValueKey(medicines[index].id),  // 使用 key
        );
      },
    );
  }
}

// 列表项使用 RepaintBoundary 隔离重绘
class MedicineListItem extends StatelessWidget {
  final Medicine medicine;
  const MedicineListItem({required this.medicine, Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: ListTile(
        leading: CircleAvatar(child: Text(medicine.name[0])),
        title: Text(medicine.name),
        subtitle: Text(medicine.dosage),
      ),
    );
  }
}
```

### 3.3 图片优化

```dart
class OptimizedImage extends StatelessWidget {
  final String url;
  final double width;
  final double height;

  OptimizedImage({required this.url, this.width = 100, this.height = 100});

  @override
  Widget build(BuildContext context) {
    return CachedNetworkImage(
      imageUrl: url,
      width: width,
      height: height,
      fit: BoxFit.cover,
      memCacheWidth: width.toInt() * 2,
      memCacheHeight: height.toInt() * 2,
      placeholder: (context, url) => Container(
        width: width,
        height: height,
        color: Colors.grey[200],
        child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
      ),
      errorWidget: (context, url, error) => Icon(Icons.error),
    );
  }
}
```

### 3.4 避免不必要的重建

```dart
// 使用 Selector 精确刷新
class MedicineCount extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Selector<MedicineBloc, int>(
      selector: (context, bloc) => bloc.state.medicines.length,
      builder: (context, count, child) {
        return Text('共 $count 种药品');
      },
    );
  }
}

// 使用 const 子 Widget
class OptimizedContainer extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      child: const _StaticContent(),  // 不会重建
    );
  }
}

class _StaticContent extends StatelessWidget {
  const _StaticContent();
  @override
  Widget build(BuildContext context) => Text('静态内容');
}
```

## 4. 内存优化

### 4.1 图片内存

```dart
// 限制图片缓存大小
class ImageCacheManager {
  static void configureCache() {
    PaintingBinding.instance.imageCache.maximumSize = 100;
    PaintingBinding.instance.imageCache.maximumSizeBytes = 50 * 1024 * 1024;
  }
}

// 及时释放图片
class DisposableImage extends StatefulWidget {
  final String url;
  DisposableImage({required this.url});

  @override
  _DisposableImageState createState() => _DisposableImageState();
}

class _DisposableImageState extends State<DisposableImage> {
  @override
  void dispose() {
    PaintingBinding.instance.imageCache.evict(NetworkImage(widget.url));
    super.dispose();
  }
}
```

### 4.2 控制器释放

```dart
class MyPage extends StatefulWidget {
  @override
  _MyPageState createState() => _MyPageState();
}

class _MyPageState extends State<MyPage> {
  late final TextEditingController _controller;
  late final ScrollController _scrollController;
  late final StreamSubscription _subscription;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController();
    _scrollController = ScrollController();
    _subscription = stream.listen(_onData);
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    _subscription.cancel();
    super.dispose();
  }
}
```

### 4.3 内存泄漏检测

```dart
class MemoryLeakDetector {
  static void init() {
    if (kDebugMode) {
      Timer.periodic(Duration(seconds: 30), (_) {
        _checkMemory();
      });
    }
  }

  static void _checkMemory() {
    // 检查是否有未释放的资源
  }
}
```

## 5. 网络优化

### 5.1 请求合并

```dart
class BatchRequestService {
  final Map<String, Completer> _pending = {};
  final Duration _batchWindow = Duration(milliseconds: 50);

  Future<T> request<T>(String key, Future<T> Function() request) {
    if (_pending.containsKey(key)) {
      return _pending[key]!.future as Future<T>;
    }

    final completer = Completer<T>();
    _pending[key] = completer;

    Future.delayed(_batchWindow, () async {
      try {
        final result = await request();
        completer.complete(result);
      } catch (e) {
        completer.completeError(e);
      }
      _pending.remove(key);
    });

    return completer.future;
  }
}
```

### 5.2 数据缓存

```dart
class NetworkCache {
  final Map<String, CacheEntry> _cache = {};
  final Duration _defaultTtl = Duration(minutes: 5);

  Future<T> get<T>(
    String key,
    Future<T> Function() fetch, {
    Duration? ttl,
  }) async {
    final entry = _cache[key];
    if (entry != null && !entry.isExpired) {
      return entry.value as T;
    }

    final value = await fetch();
    _cache[key] = CacheEntry(value, ttl ?? _defaultTtl);
    return value;
  }
}
```

## 6. 包体积优化

### 6.1 资源优化

```yaml
# 压缩图片
# 使用 tinypng 或类似工具压缩
# 使用 WebP 格式

# pubspec.yaml
flutter:
  assets:
    - assets/images/
```

### 6.2 代码优化

```bash
# 构建优化
flutter build apk --release --obfuscate --split-debug-info=./debug-info

# 按 ABI 拆分
flutter build apk --release --split-per-abi
```

### 6.3 依赖优化

```yaml
# 只引入需要的功能
dependencies:
  firebase_auth: ^4.0.0
  # 不需要的不引入
```

## 7. 性能监控

### 7.1 性能埋点

```dart
class PerformanceMonitor {
  static final Stopwatch _startupStopwatch = Stopwatch();

  static void startStartupTracking() {
    _startupStopwatch.start();
  }

  static void endStartupTracking() {
    _startupStopwatch.stop();
    final duration = _startupStopwatch.elapsedMilliseconds;
    AnalyticsService.instance.logEvent(
      'startup_time',
      parameters: {'duration': duration},
    );
  }

  static void trackPageLoad(String pageName, int durationMs) {
    AnalyticsService.instance.logEvent(
      'page_load',
      parameters: {'page': pageName, 'duration': durationMs},
    );
  }
}
```

## 8. 性能优化检查清单

- [ ] 冷启动优化
- [ ] 延迟初始化
- [ ] 预加载
- [ ] 启动页优化
- [ ] Widget 优化
- [ ] 列表优化
- [ ] 图片优化
- [ ] 避免重建
- [ ] 内存优化
- [ ] 控制器释放
- [ ] 网络优化
- [ ] 包体积优化

---

*极致的性能是用户体验的保障。启动加速、流畅渲染、低内存占用，让 APP 运行如丝般顺滑。*
