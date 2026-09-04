# APP图片加载与缓存设计

> 本文档是家健镜系统 APP 图片加载与缓存的完整设计说明，覆盖图片加载、内存缓存、磁盘缓存、图片处理、预加载。

## 1. 概述

### 1.1 设计目标

1. 快速加载：图片加载 < 200ms
2. 节省流量：缓存命中率 > 80%
3. 内存可控：图片内存 < 50MB
4. 流畅滚动：列表滚动不卡顿
5. 支持多种格式：JPG、PNG、WebP、GIF

### 1.2 缓存策略

| 层级 | 存储 | 容量 | 淘汰策略 |
| --- | --- | --- | --- |
| 内存缓存 | LRU Map | 20MB | LRU |
| 磁盘缓存 | 文件系统 | 200MB | LRU + TTL |
| 网络 | CDN | - | - |

## 2. 图片加载

### 2.1 图片加载器

```dart
class ImageLoader {
  static final ImageLoader _instance = ImageLoader._internal();
  factory ImageLoader() => _instance;
  ImageLoader._internal();

  final MemoryCache _memoryCache = MemoryCache(maxSize: 20 * 1024 * 1024);
  final DiskCache _diskCache = DiskCache(maxSize: 200 * 1024 * 1024);

  Future<ui.Image> load(String url, {double? width, double? height}) async {
    final cacheKey = _generateCacheKey(url, width, height);

    // 1. 查内存缓存
    final memoryImage = _memoryCache.get(cacheKey);
    if (memoryImage != null) {
      return memoryImage;
    }

    // 2. 查磁盘缓存
    final diskBytes = await _diskCache.get(cacheKey);
    if (diskBytes != null) {
      final image = await _decodeImage(diskBytes, width, height);
      _memoryCache.set(cacheKey, image);
      return image;
    }

    // 3. 网络下载
    final bytes = await _download(url);

    // 4. 写磁盘缓存
    await _diskCache.set(cacheKey, bytes);

    // 5. 解码
    final image = await _decodeImage(bytes, width, height);
    _memoryCache.set(cacheKey, image);

    return image;
  }

  String _generateCacheKey(String url, double? width, double? height) {
    return '${url}_${width ?? 0}_${height ?? 0}';
  }

  Future<List<int>> _download(String url) async {
    final response = await http.get(Uri.parse(url));
    if (response.statusCode != 200) {
      throw ImageLoadException('下载失败: ${response.statusCode}');
    }
    return response.bodyBytes;
  }

  Future<ui.Image> _decodeImage(List<int> bytes, double? width, double? height) async {
    final codec = await ui.instantiateImageCodec(
      bytes,
      targetWidth: width?.toInt(),
      targetHeight: height?.toInt(),
    );
    final frame = await codec.getNextFrame();
    return frame.image;
  }
}
```

### 2.2 图片组件

```dart
class CachedNetworkImage extends StatefulWidget {
  final String imageUrl;
  final double? width;
  final double? height;
  final BoxFit fit;
  final Widget? placeholder;
  final Widget? errorWidget;

  CachedNetworkImage({
    required this.imageUrl,
    this.width,
    this.height,
    this.fit = BoxFit.cover,
    this.placeholder,
    this.errorWidget,
  });

  @override
  _CachedNetworkImageState createState() => _CachedNetworkImageState();
}

class _CachedNetworkImageState extends State<CachedNetworkImage> {
  ui.Image? _image;
  bool _isLoading = true;
  bool _hasError = false;

  @override
  void initState() {
    super.initState();
    _loadImage();
  }

  Future<void> _loadImage() async {
    try {
      final image = await ImageLoader().load(
        widget.imageUrl,
        width: widget.width,
        height: widget.height,
      );
      if (mounted) {
        setState(() {
          _image = image;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _hasError = true;
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return widget.placeholder ?? CircularProgressIndicator();
    }

    if (_hasError) {
      return widget.errorWidget ?? Icon(Icons.broken_image);
    }

    return RawImage(
      image: _image,
      width: widget.width,
      height: widget.height,
      fit: widget.fit,
    );
  }
}
```

## 3. 内存缓存

### 3.1 LRU 内存缓存

```dart
class MemoryCache {
  final int maxSize;
  final Map<String, _CacheEntry> _cache = {};
  int _currentSize = 0;

  MemoryCache({required this.maxSize});

  ui.Image? get(String key) {
    final entry = _cache[key];
    if (entry != null) {
      // 移到最后（最近使用）
      _cache.remove(key);
      _cache[key] = entry;
      return entry.image;
    }
    return null;
  }

  void set(String key, ui.Image image) {
    final size = _getImageSize(image);

    // 如果已存在，先移除旧的
    if (_cache.containsKey(key)) {
      _currentSize -= _cache[key]!.size;
      _cache.remove(key);
    }

    // 淘汰旧数据
    while (_currentSize + size > maxSize && _cache.isNotEmpty) {
      final oldestKey = _cache.keys.first;
      _currentSize -= _cache[oldestKey]!.size;
      _cache.remove(oldestKey);
    }

    _cache[key] = _CacheEntry(image: image, size: size);
    _currentSize += size;
  }

  void remove(String key) {
    final entry = _cache.remove(key);
    if (entry != null) {
      _currentSize -= entry.size;
    }
  }

  void clear() {
    _cache.clear();
    _currentSize = 0;
  }

  int _getImageSize(ui.Image image) {
    return image.width * image.height * 4; // RGBA
  }
}

class _CacheEntry {
  final ui.Image image;
  final int size;

  _CacheEntry({required this.image, required this.size});
}
```

## 4. 磁盘缓存

### 4.1 磁盘缓存实现

```dart
class DiskCache {
  final int maxSize;
  late final Directory _cacheDir;
  final Map<String, _DiskCacheEntry> _index = {};

  DiskCache({required this.maxSize});

  Future<void> init() async {
    final appDir = await getTemporaryDirectory();
    _cacheDir = Directory('${appDir.path}/image_cache');
    if (!await _cacheDir.exists()) {
      await _cacheDir.create(recursive: true);
    }
    await _loadIndex();
  }

  Future<List<int>?> get(String key) async {
    final entry = _index[key];
    if (entry == null) return null;

    // 检查是否过期
    if (entry.isExpired) {
      await remove(key);
      return null;
    }

    final file = File('${_cacheDir.path}/${entry.filename}');
    if (await file.exists()) {
      // 更新访问时间
      entry.lastAccess = DateTime.now();
      await _saveIndex();
      return await file.readAsBytes();
    }

    return null;
  }

  Future<void> set(String key, List<int> bytes, {Duration ttl = const Duration(days: 7)}) async {
    final filename = _generateFilename(key);
    final file = File('${_cacheDir.path}/$filename');
    await file.writeAsBytes(bytes);

    _index[key] = _DiskCacheEntry(
      filename: filename,
      size: bytes.length,
      createdAt: DateTime.now(),
      lastAccess: DateTime.now(),
      ttl: ttl,
    );

    // 淘汰旧数据
    await _evictIfNeeded();
    await _saveIndex();
  }

  Future<void> remove(String key) async {
    final entry = _index.remove(key);
    if (entry != null) {
      final file = File('${_cacheDir.path}/${entry.filename}');
      if (await file.exists()) {
        await file.delete();
      }
    }
  }

  Future<void> _evictIfNeeded() async {
    int totalSize = _index.values.fold(0, (sum, e) => sum + e.size);

    while (totalSize > maxSize && _index.isNotEmpty) {
      // 按最后访问时间排序，删除最旧的
      final sortedKeys = _index.keys.toList()
        ..sort((a, b) => _index[a]!.lastAccess.compareTo(_index[b]!.lastAccess));

      final oldestKey = sortedKeys.first;
      totalSize -= _index[oldestKey]!.size;
      await remove(oldestKey);
    }
  }
}
```

## 5. 图片处理

### 5.1 图片压缩

```dart
class ImageProcessor {
  Future<List<int>> compress(List<int> bytes, {int quality = 80, int? maxWidth}) async {
    final image = await decodeImageFromList(bytes);

    // 缩放
    if (maxWidth != null && image.width > maxWidth) {
      final scale = maxWidth / image.width;
      final targetHeight = (image.height * scale).toInt();
      // 使用 image 包进行缩放
    }

    // 压缩为 WebP
    final compressed = await _encodeWebP(image, quality: quality);
    return compressed;
  }

  Future<List<int>> _encodeWebP(ui.Image image, {int quality = 80}) async {
    final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
    // 使用 flutter_image_compress 或其他库
    return byteData!.buffer.asUint8List();
  }
}
```

### 5.2 圆角、裁剪

```dart
class ImageTransform {
  static Widget circular(String url, {double size = 48}) {
    return ClipOval(
      child: CachedNetworkImage(
        imageUrl: url,
        width: size,
        height: size,
        fit: BoxFit.cover,
      ),
    );
  }

  static Widget rounded(String url, {double radius = 8, double? width, double? height}) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: CachedNetworkImage(
        imageUrl: url,
        width: width,
        height: height,
        fit: BoxFit.cover,
      ),
    );
  }
}
```

## 6. 预加载

### 6.1 列表预加载

```dart
class PreloadListView extends StatefulWidget {
  final List<String> imageUrls;
  final int preloadCount;

  PreloadListView({required this.imageUrls, this.preloadCount = 3});

  @override
  _PreloadListViewState createState() => _PreloadListViewState();
}

class _PreloadListViewState extends State<PreloadListView> {
  final Set<String> _preloaded = {};

  void _preload(int index) {
    final end = (index + widget.preloadCount).clamp(0, widget.imageUrls.length);
    for (int i = index; i < end; i++) {
      final url = widget.imageUrls[i];
      if (!_preloaded.contains(url)) {
        _preloaded.add(url);
        ImageLoader().load(url);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      itemCount: widget.imageUrls.length,
      itemBuilder: (context, index) {
        _preload(index);
        return CachedNetworkImage(imageUrl: widget.imageUrls[index]);
      },
    );
  }
}
```

## 7. 图片加载检查清单

- [ ] 图片加载器
- [ ] 图片组件
- [ ] 内存缓存
- [ ] 磁盘缓存
- [ ] 图片压缩
- [ ] 图片变换
- [ ] 预加载
- [ ] 占位图
- [ ] 错误处理
- [ ] 内存控制
- [ ] 缓存淘汰
- [ ] 格式支持

---

*流畅的图片体验是 APP 的门面。智能缓存、高效加载，让每张图片都瞬间呈现。*
