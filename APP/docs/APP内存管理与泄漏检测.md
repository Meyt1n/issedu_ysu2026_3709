# APP内存管理与泄漏检测

> 本文档是家健镜系统 APP 内存管理与泄漏检测的完整设计说明，覆盖内存优化、泄漏检测、图片内存、对象池、监控告警。

## 1. 概述

### 1.1 设计目标

1. 内存占用 < 150MB
2. 无内存泄漏
3. 低内存时自动清理
4. OOM 率 < 0.01%
5. 内存可监控

### 1.2 内存区域

| 区域 | 说明 | 优化重点 |
| --- | --- | --- |
| 堆内存 | 对象分配 | 减少对象创建 |
| 方法区 | 类信息、常量 | 类加载管理 |
| 位图内存 | 图片解码 | 图片压缩、复用 |
| 栈内存 | 方法调用 | 避免深递归 |

## 2. 内存优化

### 2.1 对象复用

```dart
class ObjectPool<T> {
  final List<T> _pool = [];
  final int _maxSize;
  final T Function() _creator;

  ObjectPool({required T Function() creator, int maxSize = 50})
      : _creator = creator,
        _maxSize = maxSize;

  T acquire() {
    if (_pool.isNotEmpty) {
      return _pool.removeLast();
    }
    return _creator();
  }

  void release(T object) {
    if (_pool.length < _maxSize) {
      _pool.add(object);
    }
  }

  void clear() {
    _pool.clear();
  }
}

// 使用示例
class TextEditingControllerPool {
  static final ObjectPool<TextEditingController> _pool = ObjectPool(
    creator: () => TextEditingController(),
    maxSize: 20,
  );

  static TextEditingController acquire() => _pool.acquire();
  static void release(TextEditingController controller) {
    controller.clear();
    _pool.release(controller);
  }
}
```

### 2.2 列表优化

```dart
class EfficientListView extends StatelessWidget {
  final List<Item> items;

  EfficientListView({required this.items});

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      itemCount: items.length,
      itemExtent: 80, // 固定高度，避免重复计算
      itemBuilder: (context, index) {
        return ItemWidget(item: items[index]);
      },
    );
  }
}

// 避免在 build 中创建对象
// 不好
Widget build(BuildContext context) {
  final formatter = DateFormat('yyyy-MM-dd'); // 每次 build 都创建
  return Text(formatter.format(date));
}

// 好
final _formatter = DateFormat('yyyy-MM-dd'); // 成员变量
Widget build(BuildContext context) {
  return Text(_formatter.format(date));
}
```

### 2.3 常量提升

```dart
class Constants {
  static const EdgeInsets padding = EdgeInsets.all(16);
  static const BorderRadius borderRadius = BorderRadius.all(Radius.circular(8));
  static const TextStyle titleStyle = TextStyle(
    fontSize: 18,
    fontWeight: FontWeight.bold,
  );
}

// 使用
Container(
  padding: Constants.padding,
  decoration: BoxDecoration(borderRadius: Constants.borderRadius),
  child: Text('标题', style: Constants.titleStyle),
)
```

## 3. 图片内存优化

### 3.1 图片采样

```dart
class ImageResizer {
  static Future<Uint8List> resizeImage(
    String path, {
    int targetWidth = 1080,
    int quality = 80,
  }) async {
    final image = await decodeImageFromList(await File(path).readAsBytes());

    // 计算采样比
    final scale = targetWidth / image.width;
    final targetHeight = (image.height * scale).toInt();

    // 使用 image 包进行缩放
    final resized = copyResize(
      decodeImage(await File(path).readAsBytes())!,
      width: targetWidth,
      height: targetHeight,
    );

    return encodeJpg(resized, quality: quality);
  }
}
```

### 3.2 图片缓存限制

```dart
class LimitedImageCache extends ImageCache {
  @override
  set maximumSize(int value) {
    super.maximumSize = 100; // 最多缓存 100 张
  }

  @override
  set maximumSizeBytes(int value) {
    super.maximumSizeBytes = 50 * 1024 * 1024; // 最多 50MB
  }
}

// 初始化
void main() {
  PaintingBinding.instance.imageCache.maximumSize = 100;
  PaintingBinding.instance.imageCache.maximumSizeBytes = 50 << 20;
}
```

### 3.3 图片释放

```dart
class MemoryAwareImage extends StatefulWidget {
  final String imageUrl;

  MemoryAwareImage({required this.imageUrl});

  @override
  _MemoryAwareImageState createState() => _MemoryAwareImageState();
}

class _MemoryAwareImageState extends State<MemoryAwareImage> with RouteAware {
  ImageStream? _imageStream;
  ImageInfo? _imageInfo;

  @override
  void didPopNext() {
    // 页面重新可见时重新加载
    _loadImage();
  }

  @override
  void didPushNext() {
    // 页面不可见时释放图片
    _disposeImage();
  }

  @override
  void dispose() {
    _disposeImage();
    super.dispose();
  }

  void _disposeImage() {
    _imageInfo?.image.dispose();
    _imageInfo = null;
  }
}
```

## 4. 内存泄漏检测

### 4.1 泄漏检测工具

```dart
class MemoryLeakDetector {
  final Map<String, WeakReference> _trackedObjects = {};

  void track(Object object, String name) {
    _trackedObjects[name] = WeakReference(object);
  }

  Map<String, bool> checkLeaks() {
    final results = <String, bool>{};
    _trackedObjects.forEach((name, ref) {
      results[name] = ref.target != null; // true 表示仍存活（可能泄漏）
    });
    return results;
  }

  void forceGC() {
    // 触发 GC（Flutter 中无法直接触发，通过分配大量对象间接触发）
    final list = List.generate(100000, (i) => i);
    list.clear();
  }
}
```

### 4.2 常见泄漏场景

```dart
// 1. 定时器未取消
class BadWidget extends StatefulWidget {
  @override
  _BadWidgetState createState() => _BadWidgetState();
}

class _BadWidgetState extends State<BadWidget> {
  late Timer _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(Duration(seconds: 1), (_) {
      // 持有 this 引用
      setState(() {});
    });
  }

  // 缺少 dispose！
  // @override
  // void dispose() {
  //   _timer.cancel();
  //   super.dispose();
  // }
}

// 2. 单例持有 Context
class BadSingleton {
  static BuildContext? _context;

  static void setContext(BuildContext context) {
    _context = context; // 持有 Activity 引用，导致泄漏
  }
}

// 3. 回调未移除
class BadListener extends StatefulWidget {
  @override
  _BadListenerState createState() => _BadListenerState();
}

class _BadListenerState extends State<BadListener> {
  @override
  void initState() {
    super.initState();
    EventBus().on<DataEvent>().listen((event) {
      // 持有 this
    });
    // 缺少取消订阅！
  }
}
```

### 4.3 正确写法

```dart
class GoodWidget extends StatefulWidget {
  @override
  _GoodWidgetState createState() => _GoodWidgetState();
}

class _GoodWidgetState extends State<GoodWidget> {
  late Timer _timer;
  StreamSubscription? _subscription;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });

    _subscription = EventBus().on<DataEvent>().listen((event) {
      if (mounted) {
        // 处理事件
      }
    });
  }

  @override
  void dispose() {
    _timer.cancel();
    _subscription?.cancel();
    super.dispose();
  }
}
```

## 5. 低内存处理

### 5.1 内存警告监听

```dart
class MemoryManager with WidgetsBindingObserver {
  static final MemoryManager instance = MemoryManager._();
  MemoryManager._();

  void init() {
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didHaveMemoryPressure() {
    // 系统内存不足，清理缓存
    _clearMemoryCache();
  }

  void _clearMemoryCache() {
    // 清理图片缓存
    PaintingBinding.instance.imageCache.clear();
    PaintingBinding.instance.imageCache.clearLiveImages();

    // 清理数据缓存
    CacheManager.instance.clearMemoryCache();

    // 清理对象池
    ObjectPoolManager.instance.clearAll();
  }
}
```

### 5.2 内存状态检查

```dart
class MemoryStatus {
  static Future<MemoryInfo> getMemoryInfo() async {
    final memoryInfo = await SystemChannels.platform.invokeMethod('SystemNavigator.pop');
    // 使用 device_info 或 system_info 插件获取真实内存信息
    return MemoryInfo(
      totalMemory: 4 * 1024 * 1024 * 1024, // 4GB
      freeMemory: 1 * 1024 * 1024 * 1024, // 1GB
      usedMemory: 3 * 1024 * 1024 * 1024, // 3GB
    );
  }

  static bool isLowMemory() {
    // 简化判断
    return false;
  }
}
```

## 6. 内存监控

### 6.1 内存指标采集

```dart
class MemoryMonitor {
  Timer? _timer;
  final List<MemorySnapshot> _snapshots = [];

  void start() {
    _timer = Timer.periodic(Duration(seconds: 30), (_) {
      _snapshot();
    });
  }

  void _snapshot() {
    final snapshot = MemorySnapshot(
      timestamp: DateTime.now(),
      heapUsage: _getHeapUsage(),
      imageCacheSize: PaintingBinding.instance.imageCache.currentSizeBytes,
    );
    _snapshots.add(snapshot);

    // 内存过高上报告警
    if (snapshot.heapUsage > 150 * 1024 * 1024) {
      _reportHighMemory(snapshot);
    }
  }

  int _getHeapUsage() {
    // 使用 dart:developer 或 extension
    return 0;
  }

  void stop() {
    _timer?.cancel();
  }
}
```

### 6.2 OOM 防护

```dart
class OOMGuard {
  static Future<bool> canAllocateLargeMemory(int size) async {
    final info = await MemoryStatus.getMemoryInfo();
    return info.freeMemory > size * 2; // 预留 2 倍空间
  }

  static Future<T?> safeAllocate<T>(
    Future<T> Function() allocator, {
    required T fallback,
  }) async {
    try {
      return await allocator();
    } catch (e) {
      if (e is OutOfMemoryError) {
        // 清理缓存后重试
        MemoryManager.instance._clearMemoryCache();
        try {
          return await allocator();
        } catch (_) {
          return fallback;
        }
      }
      rethrow;
    }
  }
}
```

## 7. 内存管理检查清单

- [ ] 对象复用
- [ ] 列表优化
- [ ] 常量提升
- [ ] 图片采样
- [ ] 图片缓存限制
- [ ] 图片释放
- [ ] 泄漏检测
- [ ] 定时器管理
- [ ] 回调管理
- [ ] 低内存处理
- [ ] 内存监控
- [ ] OOM 防护

---

*高效的内存管理是 APP 流畅运行的保障。精打细算、及时释放，让内存用在刀刃上。*
