# APP性能优化指南

> 本文档是家健镜 APP 性能优化的完整指南，覆盖启动优化、渲染性能、内存优化、网络优化、存储优化、性能监控。面向移动端开发者，作为性能优化的权威依据。

## 1. 性能目标

### 1.1 核心指标

| 指标 | 目标 | 说明 |
| --- | --- | --- |
| 冷启动时间 | <2s | 从点击图标到首页可交互 |
| 热启动时间 | <500ms | 从后台恢复到前台 |
| 页面切换 | <300ms | 页面转场动画流畅 |
| 列表滚动 | 60fps | 无掉帧 |
| 内存峰值 | <200MB | 避免 OOM |
| 包体积 | <50MB | Android APK |
| 首屏渲染 | <1s | 首页内容可见 |

### 1.2 性能预算

```dart
class PerformanceBudget {
  static const Duration coldStart = Duration(seconds: 2);
  static const Duration warmStart = Duration(milliseconds: 500);
  static const Duration pageTransition = Duration(milliseconds: 300);
  static const int targetFPS = 60;
  static const int maxMemoryMB = 200;
  static const int maxAppSizeMB = 50;
  static const Duration apiTimeout = Duration(seconds: 10);
  static const int maxImageCacheMB = 100;
}
```

## 2. 启动优化

### 2.1 懒加载

```dart
// 不好：启动时初始化所有服务
void main() {
  final apiClient = ApiClient();
  final database = Database();
  final notificationService = NotificationService();
  final analytics = AnalyticsService();
  // ... 更多初始化
  runApp(MyApp());
}

// 好：使用 get_it 懒加载
final getIt = GetIt.instance;

void setupDependencies() {
  getIt.registerLazySingleton<ApiClient>(() => ApiClient());
  getIt.registerLazySingleton<Database>(() => Database());
  getIt.registerLazySingleton<NotificationService>(
    () => NotificationService(),
  );
}

void main() {
  setupDependencies();
  runApp(MyApp());
}
```

### 2.2 异步初始化

```dart
class AppInitializer {
  static Future<void> preloadCritical() async {
    // 关键路径：必须在启动时完成
    await HiveService.init();
    await SecureStorageService.init();
  }

  static Future<void> preloadNonCritical() async {
    // 非关键：后台异步初始化
    await NotificationService.init();
    await AnalyticsService.init();
    await PushNotificationService.init();
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 关键初始化
  await AppInitializer.preloadCritical();

  runApp(const MyApp());

  // 非关键初始化（不阻塞启动）
  AppInitializer.preloadNonCritical();
}
```

### 2.3 启动页优化

```dart
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _initialize();
  }

  Future<void> _initialize() async {
    // 并行执行初始化任务
    await Future.wait([
      _loadUserSession(),
      _precacheImages(),
      _warmUpDatabase(),
    ]);

    if (mounted) {
      context.go(AppRoutes.home);
    }
  }

  Future<void> _precacheImages() async {
    await precacheImage(const AssetImage('assets/logo.png'), context);
  }
}
```

## 3. 渲染性能

### 3.1 减少 Widget 重建

```dart
// 不好：整个页面重建
class _HomePageState extends State<HomePage> {
  int _counter = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          VeryComplexWidget(), // 每次都重建
          Text('$_counter'),
          ElevatedButton(
            onPressed: () => setState(() => _counter++),
            child: const Text('+1'),
          ),
        ],
      ),
    );
  }
}

// 好：将变化部分提取到独立 StatefulWidget
class CounterWidget extends StatefulWidget {
  const CounterWidget({super.key});

  @override
  State<CounterWidget> createState() => _CounterWidgetState();
}

class _CounterWidgetState extends State<CounterWidget> {
  int _counter = 0;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text('$_counter'),
        ElevatedButton(
          onPressed: () => setState(() => _counter++),
          child: const Text('+1'),
        ),
      ],
    );
  }
}
```

### 3.2 使用 const 构造函数

```dart
// 不好：每次创建新实例
Padding(padding: EdgeInsets.all(16), child: Text('Hello'));

// 好：const 实例复用
const Padding(padding: EdgeInsets.all(16), child: Text('Hello'));
```

### 3.3 列表优化

```dart
// 不好：一次性构建所有子项
ListView(
  children: items.map((item) => ItemWidget(item: item)).toList(),
)

// 好：ListView.builder 懒加载
ListView.builder(
  itemCount: items.length,
  itemBuilder: (context, index) => ItemWidget(item: items[index]),
)

// 更好：使用 RepaintBoundary 隔离重绘
ListView.builder(
  itemCount: items.length,
  itemBuilder: (context, index) => RepaintBoundary(
    child: ItemWidget(item: items[index]),
  ),
)
```

### 3.4 图片优化

```dart
class OptimizedImage extends StatelessWidget {
  final String url;
  final double width;
  final double height;

  const OptimizedImage({
    super.key,
    required this.url,
    required this.width,
    required this.height,
  });

  @override
  Widget build(BuildContext context) {
    return CachedNetworkImage(
      imageUrl: url,
      width: width,
      height: height,
      fit: BoxFit.cover,
      memCacheWidth: (width * MediaQuery.of(context).devicePixelRatio).toInt(),
      memCacheHeight: (height * MediaQuery.of(context).devicePixelRatio).toInt(),
      placeholder: (context, url) => Container(
        width: width,
        height: height,
        color: Colors.grey[200],
      ),
      errorWidget: (context, url, error) => Container(
        width: width,
        height: height,
        color: Colors.grey[200],
        child: const Icon(Icons.broken_image),
      ),
    );
  }
}
```

## 4. 内存优化

### 4.1 图片缓存管理

```dart
class ImageCacheManager {
  static const int maxCacheSize = 100 * 1024 * 1024; // 100MB

  static void configureCache() {
    PaintingBinding.instance.imageCache.maximumSizeBytes = maxCacheSize;
  }

  static Future<void> clearCache() async {
    PaintingBinding.instance.imageCache.clear();
    await CachedNetworkImage.evictFromCache('');
  }
}
```

### 4.2 流和控制器释放

```dart
class MyWidget extends StatefulWidget {
  const MyWidget({super.key});

  @override
  State<MyWidget> createState() => _MyWidgetState();
}

class _MyWidgetState extends State<MyWidget> {
  final StreamController<int> _controller = StreamController<int>();
  late final AnimationController _animationController;
  late final ScrollController _scrollController;

  @override
  void initState() {
    super.initState();
    _animationController = AnimationController(vsync: this);
    _scrollController = ScrollController();
  }

  @override
  void dispose() {
    _controller.close();
    _animationController.dispose();
    _scrollController.dispose();
    super.dispose();
  }
}
```

### 4.3 大列表数据管理

```dart
class PaginationController<T> extends ChangeNotifier {
  final List<T> _items = [];
  bool _isLoading = false;
  bool _hasMore = true;
  int _page = 0;
  static const int pageSize = 20;

  List<T> get items => List.unmodifiable(_items);
  bool get isLoading => _isLoading;
  bool get hasMore => _hasMore;

  Future<void> loadMore() async {
    if (_isLoading || !_hasMore) return;
    _isLoading = true;
    notifyListeners();

    try {
      final newItems = await fetchData(page: _page, size: pageSize);
      if (newItems.length < pageSize) {
        _hasMore = false;
      }
      _items.addAll(newItems);
      _page++;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _items.clear();
    super.dispose();
  }
}
```

## 5. 网络优化

### 5.1 请求合并

```dart
class RequestBatcher {
  final Map<String, List<Completer>> _pending = {};
  final Duration batchWindow = const Duration(milliseconds: 50);

  Future<T> batch<T>(String key, Future<T> Function() request) {
    final completer = Completer<T>();
    _pending.putIfAbsent(key, () => []).add(completer);

    if (_pending[key]!.length == 1) {
      Future.delayed(batchWindow, () => _executeBatch(key, request));
    }

    return completer.future;
  }

  Future<void> _executeBatch<T>(String key, Future<T> Function() request) async {
    final completers = _pending.remove(key)!;
    try {
      final result = await request();
      for (final c in completers) {
        c.complete(result);
      }
    } catch (e) {
      for (final c in completers) {
        c.completeError(e);
      }
    }
  }
}
```

### 5.2 缓存策略

```dart
class CachePolicy {
  static const Duration shortCache = Duration(minutes: 5);
  static const Duration mediumCache = Duration(hours: 1);
  static const Duration longCache = Duration(days: 7);

  // 药品列表：短缓存
  static const medicineList = shortCache;
  // 成员信息：中缓存
  static const memberInfo = mediumCache;
  // 药品说明书：长缓存
  static const medicineInfo = longCache;
}
```

## 6. 存储优化

### 6.1 缓存清理

```dart
class CacheCleaner {
  static Future<void> cleanExpired() async {
    final tempDir = await getTemporaryDirectory();
    final now = DateTime.now();

    await for (final entity in tempDir.list(recursive: true)) {
      if (entity is File) {
        final stat = await entity.stat();
        if (now.difference(stat.modified) > const Duration(days: 7)) {
          await entity.delete();
        }
      }
    }
  }

  static Future<int> getCacheSize() async {
    final tempDir = await getTemporaryDirectory();
    var total = 0;
    await for (final entity in tempDir.list(recursive: true)) {
      if (entity is File) {
        total += await entity.length();
      }
    }
    return total;
  }
}
```

## 7. 性能监控

### 7.1 FPS 监控

```dart
class FPSMonitor {
  static void start() {
    WidgetsBinding.instance.addTimingsCallback((timings) {
      for (final timing in timings) {
        final frameTime = timing.totalSpan.inMicroseconds / 1000;
        if (frameTime > 16.7) {
          debugPrint('掉帧: ${frameTime}ms');
        }
      }
    });
  }
}
```

### 7.2 性能埋点

```dart
class PerformanceTracker {
  static final Stopwatch _stopwatch = Stopwatch();

  static void startTrace(String name) {
    _stopwatch.reset();
    _stopwatch.start();
  }

  static void endTrace(String name) {
    _stopwatch.stop();
    final duration = _stopwatch.elapsedMilliseconds;
    debugPrint('$name: ${duration}ms');
    // 上报到性能监控平台
  }
}
```

## 8. 包体积优化

### 8.1 资源压缩

```yaml
# pubspec.yaml
flutter:
  assets:
    - assets/images/
    - assets/icons/

# 使用 WebP 代替 PNG
# 使用 SVG 代替多分辨率 PNG
# 删除未使用的资源
```

### 8.2 代码混淆

```yaml
# android/app/build.gradle
buildTypes {
    release {
        minifyEnabled true
        shrinkResources true
        proguardFiles getDefaultProguardFile('proguard-android.txt'), 'proguard-rules.pro'
    }
}
```

## 9. 性能检查清单

- [ ] 冷启动 <2s
- [ ] 热启动 <500ms
- [ ] 列表滚动 60fps
- [ ] 页面切换流畅
- [ ] 内存 <200MB
- [ ] 图片缓存有大小限制
- [ ] 控制器正确释放
- [ ] 列表懒加载
- [ ] 图片按需加载
- [ ] 网络请求有缓存
- [ ] 过期缓存自动清理
- [ ] 包体积 <50MB
- [ ] 性能监控埋点
- [ ] 大图片压缩
- [ ] const 构造函数使用

---

*性能是体验的底线。每一次优化，都是对用户时间的尊重。*
