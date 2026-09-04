# APP数据缓存策略设计

> 本文档是家健镜系统 APP 数据缓存策略的完整设计说明，覆盖缓存层级、缓存策略、缓存失效、缓存同步、性能优化。

## 1. 概述

### 1.1 设计目标

1. 快速响应：缓存命中 < 10ms
2. 离线可用：无网络时可浏览缓存数据
3. 数据一致：缓存与服务端最终一致
4. 内存可控：缓存占用不超过 100MB
5. 智能预取：提前缓存用户可能需要的数据

### 1.2 缓存层级

| 层级 | 存储 | 容量 | 速度 | 用途 |
| --- | --- | --- | --- | --- |
| L1 内存缓存 | Map | 10MB | 极快 | 热点数据 |
| L2 磁盘缓存 | SQLite | 100MB | 快 | 结构化数据 |
| L3 文件缓存 | 文件系统 | 500MB | 中 | 图片、文件 |

## 2. 内存缓存

### 2.1 LRU 缓存

```dart
class LRUCache<K, V> {
  final int maxSize;
  final Map<K, V> _cache = {};
  final List<K> _accessOrder = [];

  LRUCache({this.maxSize = 100});

  V? get(K key) {
    if (_cache.containsKey(key)) {
      _accessOrder.remove(key);
      _accessOrder.add(key);
      return _cache[key];
    }
    return null;
  }

  void set(K key, V value) {
    if (_cache.containsKey(key)) {
      _accessOrder.remove(key);
    } else if (_cache.length >= maxSize) {
      final oldest = _accessOrder.removeAt(0);
      _cache.remove(oldest);
    }
    _cache[key] = value;
    _accessOrder.add(key);
  }

  void remove(K key) {
    _cache.remove(key);
    _accessOrder.remove(key);
  }

  void clear() {
    _cache.clear();
    _accessOrder.clear();
  }
}
```

### 2.2 带过期的缓存

```dart
class CacheEntry<V> {
  final V value;
  final DateTime createdAt;
  final Duration ttl;

  CacheEntry({
    required this.value,
    required this.createdAt,
    this.ttl = const Duration(minutes: 30),
  });

  bool get isExpired => DateTime.now().difference(createdAt) > ttl;
}

class TTLCache<K, V> {
  final Map<K, CacheEntry<V>> _cache = {};
  final int maxSize;

  TTLCache({this.maxSize = 200});

  V? get(K key) {
    final entry = _cache[key];
    if (entry == null || entry.isExpired) {
      _cache.remove(key);
      return null;
    }
    return entry.value;
  }

  void set(K key, V value, {Duration? ttl}) {
    _cache[key] = CacheEntry(
      value: value,
      createdAt: DateTime.now(),
      ttl: ttl ?? const Duration(minutes: 30),
    );
  }
}
```

## 3. 磁盘缓存

### 3.1 SQLite 缓存

```dart
class CacheDao {
  final Database _db;

  CacheDao(this._db);

  static const String tableSql = '''
    CREATE TABLE IF NOT EXISTS cache (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      type TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      expires_at INTEGER,
      hit_count INTEGER DEFAULT 0
    )
  ''';

  Future<void> set(String key, String value, {String type = 'json', Duration? ttl}) async {
    final now = DateTime.now().millisecondsSinceEpoch;
    final expiresAt = ttl != null ? now + ttl.inMilliseconds : null;

    await _db.insert(
      'cache',
      {
        'key': key,
        'value': value,
        'type': type,
        'created_at': now,
        'expires_at': expiresAt,
        'hit_count': 0,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<String?> get(String key) async {
    final now = DateTime.now().millisecondsSinceEpoch;
    final result = await _db.query(
      'cache',
      where: 'key = ? AND (expires_at IS NULL OR expires_at > ?)',
      whereArgs: [key, now],
    );

    if (result.isNotEmpty) {
      // 更新命中次数
      await _db.rawUpdate(
        'UPDATE cache SET hit_count = hit_count + 1 WHERE key = ?',
        [key],
      );
      return result.first['value'] as String;
    }
    return null;
  }

  Future<void> remove(String key) async {
    await _db.delete('cache', where: 'key = ?', whereArgs: [key]);
  }

  Future<void> clearExpired() async {
    final now = DateTime.now().millisecondsSinceEpoch;
    await _db.delete('cache', where: 'expires_at < ?', whereArgs: [now]);
  }
}
```

### 3.2 缓存管理器

```dart
class CacheManager {
  final TTLCache<String, dynamic> _memoryCache = TTLCache(maxSize: 200);
  final CacheDao _diskCache;

  CacheManager(this._diskCache);

  Future<T?> get<T>(String key) async {
    // 1. 查内存
    final memoryValue = _memoryCache.get(key);
    if (memoryValue != null) {
      return memoryValue as T;
    }

    // 2. 查磁盘
    final diskValue = await _diskCache.get(key);
    if (diskValue != null) {
      final decoded = jsonDecode(diskValue);
      _memoryCache.set(key, decoded);
      return decoded as T;
    }

    return null;
  }

  Future<void> set<T>(String key, T value, {Duration? ttl}) async {
    _memoryCache.set(key, value, ttl: ttl);
    await _diskCache.set(
      key,
      jsonEncode(value),
      ttl: ttl,
    );
  }

  Future<void> invalidate(String key) async {
    _memoryCache.remove(key);
    await _diskCache.remove(key);
  }

  Future<void> invalidatePrefix(String prefix) async {
    // 清除指定前缀的缓存
    await _diskCache.removeByPrefix(prefix);
  }
}
```

## 4. 缓存策略

### 4.1 Cache-Aside

```dart
class MedicineRepository {
  final MedicineApi _api;
  final CacheManager _cache;

  Future<List<Medicine>> getMedicines(String memberId) async {
    final cacheKey = 'medicines:$memberId';

    // 1. 查缓存
    final cached = await _cache.get<List>(cacheKey);
    if (cached != null) {
      return cached.map((e) => Medicine.fromJson(e)).toList();
    }

    // 2. 查网络
    final medicines = await _api.getMedicines(memberId);

    // 3. 写缓存
    await _cache.set(
      cacheKey,
      medicines.map((e) => e.toJson()).toList(),
      ttl: Duration(minutes: 30),
    );

    return medicines;
  }
}
```

### 4.2 Write-Through

```dart
Future<void> addMedicine(Medicine medicine) async {
  // 1. 写网络
  await _api.addMedicine(medicine);

  // 2. 更新缓存
  final cacheKey = 'medicines:${medicine.memberId}';
  final cached = await _cache.get<List>(cacheKey);
  if (cached != null) {
    cached.add(medicine.toJson());
    await _cache.set(cacheKey, cached);
  }
}
```

### 4.3 Write-Behind

```dart
class WriteBehindCache {
  final Queue<CacheOperation> _queue = Queue();
  bool _isFlushing = false;

  void enqueue(CacheOperation operation) {
    _queue.add(operation);
    _scheduleFlush();
  }

  Future<void> _scheduleFlush() async {
    if (_isFlushing) return;
    _isFlushing = true;

    await Future.delayed(Duration(seconds: 5));
    await _flush();

    _isFlushing = false;
  }

  Future<void> _flush() async {
    while (_queue.isNotEmpty) {
      final op = _queue.removeFirst();
      try {
        await op.execute();
      } catch (e) {
        // 失败重试
        _queue.add(op);
        break;
      }
    }
  }
}
```

## 5. 缓存失效

### 5.1 基于时间

```dart
// TTL 过期
_cache.set(key, value, ttl: Duration(minutes: 30));
```

### 5.2 基于事件

```dart
class CacheInvalidator {
  final CacheManager _cache;

  void onMedicineUpdated(String memberId) {
    _cache.invalidate('medicines:$memberId');
    _cache.invalidate('medicines:$memberId:today');
    _cache.invalidate('dashboard:$memberId');
  }

  void onHealthDataUpdated(String memberId) {
    _cache.invalidate('health:$memberId:latest');
    _cache.invalidate('health:$memberId:trend');
    _cache.invalidate('dashboard:$memberId');
  }
}
```

### 5.3 基于版本

```dart
class VersionedCache {
  Future<T?> get<T>(String key, int version) async {
    final versionedKey = '$key:v$version';
    return await _cache.get(versionedKey);
  }

  Future<void> set<T>(String key, int version, T value) async {
    final versionedKey = '$key:v$version';
    await _cache.set(versionedKey, value);
  }
}
```

## 6. 预取策略

### 6.1 智能预取

```dart
class PrefetchManager {
  final CacheManager _cache;
  final MedicineApi _api;

  Future<void> prefetchUserData(String memberId) async {
    // 预取首页数据
    await Future.wait([
      _prefetchMedicines(memberId),
      _prefetchHealthData(memberId),
      _prefetchReminders(memberId),
    ]);
  }

  Future<void> _prefetchMedicines(String memberId) async {
    final medicines = await _api.getMedicines(memberId);
    await _cache.set('medicines:$memberId', medicines);
  }
}
```

## 7. 缓存监控

### 7.1 命中率统计

```dart
class CacheMetrics {
  int _hits = 0;
  int _misses = 0;

  void recordHit() => _hits++;
  void recordMiss() => _misses++;

  double get hitRate => _hits / (_hits + _misses);

  Map<String, dynamic> toJson() => {
    'hits': _hits,
    'misses': _misses,
    'hit_rate': hitRate.toStringAsFixed(2),
  };
}
```

## 8. 缓存策略检查清单

- [ ] 内存缓存
- [ ] 磁盘缓存
- [ ] 缓存管理器
- [ ] Cache-Aside
- [ ] Write-Through
- [ ] Write-Behind
- [ ] 缓存失效
- [ ] 预取策略
- [ ] 缓存监控
- [ ] 命中率统计
- [ ] 内存控制
- [ ] 离线支持

---

*智能缓存是 APP 性能的关键。多级缓存、合理策略，让数据触手可及。*
