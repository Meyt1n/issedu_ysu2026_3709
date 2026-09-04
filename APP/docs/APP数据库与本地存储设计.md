# APP数据库与本地存储设计

> 本文档是家健镜 APP 本地数据库与存储的完整设计说明，覆盖 Hive 配置、数据模型、查询优化、缓存策略、数据迁移、安全存储。面向移动端开发者，作为本地存储实现的权威依据。

## 1. 本地存储概述

### 1.1 设计目标

1. **离线可用**：核心功能离线可访问
2. **快速访问**：本地查询毫秒级响应
3. **数据安全**：敏感数据加密存储
4. **空间可控**：缓存自动清理，不占用过多空间
5. **同步友好**：数据结构便于和服务端同步

### 1.2 存储方案选型

| 方案 | 适用场景 | 优点 | 缺点 |
| --- | --- | --- | --- |
| SharedPreferences | 简单键值（设置、Token） | 简单、轻量 | 只支持基本类型 |
| Hive | 结构化数据缓存 | 快、NoSQL、Dart 原生 | 不支持复杂查询 |
| SQLite (sqflite) | 复杂关系数据 | SQL 查询、事务 | 较重、需要写 SQL |
| 文件系统 | 图片、文件缓存 | 直接 | 需要自行管理 |
| Keychain/Keystore | 敏感数据（密码、密钥） | 系统级安全 | API 复杂 |

### 1.3 存储分层

```
┌─────────────────────────────────────┐
│         内存缓存 (Provider)          │  ← 最快，会话级
├─────────────────────────────────────┤
│         Hive (结构化缓存)            │  ← 快，持久化
├─────────────────────────────────────┤
│    SharedPreferences (键值配置)      │  ← 配置项
├─────────────────────────────────────┤
│      文件系统 (图片/文件缓存)         │  ← 大文件
├─────────────────────────────────────┤
│     Keychain/Keystore (敏感数据)     │  ← 加密存储
└─────────────────────────────────────┘
```

## 2. Hive 配置

### 2.1 初始化

```dart
class HiveService {
  static const String medicineBox = 'medicines';
  static const String eventBox = 'health_events';
  static const String riskBox = 'risks';
  static const String chatBox = 'chat_messages';
  static const String memberBox = 'members';
  static const String cacheBox = 'generic_cache';

  static Future<void> init() async {
    final dir = await getApplicationDocumentsDirectory();
    Hive.init(dir.path);

    // 注册 Adapter
    Hive.registerAdapter(MedicineAdapter());
    Hive.registerAdapter(HealthEventAdapter());
    Hive.registerAdapter(RiskEventAdapter());
    Hive.registerAdapter(ChatMessageAdapter());
    Hive.registerAdapter(MemberAdapter());

    // 打开 Box
    await Future.wait([
      Hive.openBox(medicineBox),
      Hive.openBox(eventBox),
      Hive.openBox(riskBox),
      Hive.openBox(chatBox),
      Hive.openBox(memberBox),
      Hive.openBox(cacheBox),
    ]);
  }

  static Box get medicines => Hive.box(medicineBox);
  static Box get events => Hive.box(eventBox);
  static Box get risks => Hive.box(riskBox);
  static Box get chats => Hive.box(chatBox);
  static Box get members => Hive.box(memberBox);
  static Box get cache => Hive.box(cacheBox);
}
```

### 2.2 数据模型

```dart
@HiveType(typeId: 0)
class Medicine extends HiveObject {
  @HiveField(0)
  final String id;

  @HiveField(1)
  final String name;

  @HiveField(2)
  final String dosage;

  @HiveField(3)
  final String frequency;

  @HiveField(4)
  final DateTime? expiryDate;

  @HiveField(5)
  final int stock;

  @HiveField(6)
  final DateTime updatedAt;

  @HiveField(7)
  final bool isPending; // 待同步

  Medicine({
    required this.id,
    required this.name,
    required this.dosage,
    required this.frequency,
    this.expiryDate,
    this.stock = 0,
    required this.updatedAt,
    this.isPending = false,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'dosage': dosage,
        'frequency': frequency,
        'expiry_date': expiryDate?.toIso8601String(),
        'stock': stock,
        'updated_at': updatedAt.toIso8601String(),
      };

  factory Medicine.fromJson(Map<String, dynamic> json) => Medicine(
        id: json['id'],
        name: json['name'],
        dosage: json['dosage'],
        frequency: json['frequency'],
        expiryDate: json['expiry_date'] != null
            ? DateTime.parse(json['expiry_date'])
            : null,
        stock: json['stock'] ?? 0,
        updatedAt: DateTime.parse(json['updated_at']),
      );
}
```

### 2.3 Adapter 生成

```dart
// medicine.g.dart（由 build_runner 生成）
class MedicineAdapter extends TypeAdapter<Medicine> {
  @override
  final int typeId = 0;

  @override
  Medicine read(BinaryReader reader) {
    final numOfFields = reader.readByte();
    final fields = <int, dynamic>{
      for (int i = 0; i < numOfFields; i++) reader.readByte(): reader.read(),
    };
    return Medicine(
      id: fields[0] as String,
      name: fields[1] as String,
      dosage: fields[2] as String,
      frequency: fields[3] as String,
      expiryDate: fields[4] as DateTime?,
      stock: fields[5] as int,
      updatedAt: fields[6] as DateTime,
      isPending: fields[7] as bool? ?? false,
    );
  }

  @override
  void write(BinaryWriter writer, Medicine obj) {
    writer
      ..writeByte(8)
      ..writeByte(0)..write(obj.id)
      ..writeByte(1)..write(obj.name)
      ..writeByte(2)..write(obj.dosage)
      ..writeByte(3)..write(obj.frequency)
      ..writeByte(4)..write(obj.expiryDate)
      ..writeByte(5)..write(obj.stock)
      ..writeByte(6)..write(obj.updatedAt)
      ..writeByte(7)..write(obj.isPending);
  }
}
```

## 3. Repository 模式

### 3.1 MedicineRepository

```dart
class MedicineRepository {
  final ApiClient _api;
  final Box _medicineBox;

  MedicineRepository(this._api, this._medicineBox);

  Future<List<Medicine>> getMedicines(String memberId,
      {bool forceRefresh = false}) async {
    if (!forceRefresh) {
      final cached = _getCachedMedicines(memberId);
      if (cached.isNotEmpty) return cached;
    }

    final response = await _api.dio.get('/members/$memberId/medications');
    final medicines = (response.data as List)
        .map((e) => Medicine.fromJson(e))
        .toList();

    await _cacheMedicines(memberId, medicines);
    return medicines;
  }

  List<Medicine> _getCachedMedicines(String memberId) {
    final data = _medicineBox.get('member_$memberId');
    if (data == null) return [];
    return (data as List).cast<Medicine>();
  }

  Future<void> _cacheMedicines(
      String memberId, List<Medicine> medicines) async {
    await _medicineBox.put('member_$memberId', medicines);
    await _medicineBox.put('member_${memberId}_cached_at', DateTime.now());
  }

  Future<Medicine> addMedicine({
    required String memberId,
    required String name,
    required String dosage,
    required String frequency,
  }) async {
    final response = await _api.dio.post(
      '/members/$memberId/medications',
      data: {
        'name': name,
        'dosage': dosage,
        'frequency': frequency,
      },
    );
    final medicine = Medicine.fromJson(response.data);

    // 更新缓存
    final cached = _getCachedMedicines(memberId);
    cached.add(medicine);
    await _cacheMedicines(memberId, cached);

    return medicine;
  }

  Future<void> deleteMedicine(String medicineId, String memberId) async {
    await _api.dio.delete('/medications/$medicineId');

    // 更新缓存
    final cached = _getCachedMedicines(memberId);
    cached.removeWhere((m) => m.id == medicineId);
    await _cacheMedicines(memberId, cached);
  }
}
```

## 4. 缓存管理

### 4.1 缓存策略

```dart
class CacheManager {
  final Box _cacheBox;
  static const Duration defaultTTL = Duration(hours: 1);

  CacheManager(this._cacheBox);

  Future<void> put(String key, dynamic data,
      {Duration? ttl}) async {
    final entry = CacheEntry(
      data: data,
      timestamp: DateTime.now(),
      ttl: ttl ?? defaultTTL,
    );
    await _cacheBox.put(key, entry);
  }

  T? get<T>(String key) {
    final entry = _cacheBox.get(key) as CacheEntry?;
    if (entry == null) return null;
    if (entry.isExpired) {
      _cacheBox.delete(key);
      return null;
    }
    return entry.data as T;
  }

  Future<void> invalidate(String key) async {
    await _cacheBox.delete(key);
  }

  Future<void> invalidatePrefix(String prefix) async {
    final keysToDelete = _cacheBox.keys
        .where((k) => k.toString().startsWith(prefix))
        .toList();
    for (final key in keysToDelete) {
      await _cacheBox.delete(key);
    }
  }

  Future<void> clearExpired() async {
    final expiredKeys = _cacheBox.keys.where((k) {
      final entry = _cacheBox.get(k) as CacheEntry?;
      return entry?.isExpired ?? false;
    }).toList();
    for (final key in expiredKeys) {
      await _cacheBox.delete(key);
    }
  }
}

@HiveType(typeId: 100)
class CacheEntry extends HiveObject {
  @HiveField(0)
  final dynamic data;

  @HiveField(1)
  final DateTime timestamp;

  @HiveField(2)
  final Duration ttl;

  CacheEntry({
    required this.data,
    required this.timestamp,
    required this.ttl,
  });

  bool get isExpired => DateTime.now().difference(timestamp) > ttl;
}
```

### 4.2 图片缓存

```dart
class ImageCacheManager {
  static const int maxCacheSize = 100 * 1024 * 1024; // 100MB
  static const Duration maxCacheAge = Duration(days: 30);

  Future<String?> getCachedImage(String url) async {
    final dir = await getTemporaryDirectory();
    final fileName = _generateFileName(url);
    final file = File('${dir.path}/images/$fileName');

    if (await file.exists()) {
      final stat = await file.stat();
      if (DateTime.now().difference(stat.modified) < maxCacheAge) {
        return file.path;
      }
      await file.delete();
    }
    return null;
  }

  Future<String> cacheImage(String url, List<int> bytes) async {
    final dir = await getTemporaryDirectory();
    final imageDir = Directory('${dir.path}/images');
    if (!await imageDir.exists()) {
      await imageDir.create(recursive: true);
    }

    final fileName = _generateFileName(url);
    final file = File('${imageDir.path}/$fileName');
    await file.writeAsBytes(bytes);

    await _cleanupIfNeeded(imageDir);
    return file.path;
  }

  Future<void> _cleanupIfNeeded(Directory dir) async {
    final files = await dir.list().toList();
    var totalSize = 0;
    for (final file in files) {
      final stat = await file.stat();
      totalSize += stat.size;
    }

    if (totalSize > maxCacheSize) {
      // 按修改时间排序，删除最旧的
      files.sort((a, b) async {
        final aStat = await a.stat();
        final bStat = await b.stat();
        return aStat.modified.compareTo(bStat.modified);
      });

      while (totalSize > maxCacheSize * 0.8 && files.isNotEmpty) {
        final oldest = files.removeAt(0);
        final stat = await oldest.stat();
        totalSize -= stat.size;
        await oldest.delete();
      }
    }
  }

  String _generateFileName(String url) {
    return sha256.convert(utf8.encode(url)).toString();
  }
}
```

## 5. 安全存储

### 5.1 敏感数据存储

```dart
class SecureStorageService {
  static const _keyAccessToken = 'access_token';
  static const _keyRefreshToken = 'refresh_token';
  static const _keyPassword = 'password';

  final FlutterSecureStorage _storage;

  SecureStorageService(this._storage);

  Future<void> saveTokens(String access, String refresh) async {
    await _storage.write(key: _keyAccessToken, value: access);
    await _storage.write(key: _keyRefreshToken, value: refresh);
  }

  Future<String?> getAccessToken() => _storage.read(key: _keyAccessToken);
  Future<String?> getRefreshToken() => _storage.read(key: _keyRefreshToken);

  Future<void> clearTokens() async {
    await _storage.delete(key: _keyAccessToken);
    await _storage.delete(key: _keyRefreshToken);
  }

  Future<void> savePassword(String password) async {
    await _storage.write(key: _keyPassword, value: password);
  }
}
```

### 5.2 数据加密

```dart
class EncryptedBox {
  // 使用 Hive 加密 Box
  static Future<Box> openEncryptedBox(String name) async {
    final secureStorage = FlutterSecureStorage();
    var encryptionKey = await secureStorage.read(key: 'hive_key');

    if (encryptionKey == null) {
      final key = Hive.generateSecureKey();
      encryptionKey = base64UrlEncode(key);
      await secureStorage.write(key: 'hive_key', value: encryptionKey);
    }

    final key = base64Url.decode(encryptionKey);
    return Hive.openBox(
      name,
      encryptionCipher: HiveAesCipher(key),
    );
  }
}
```

## 6. 数据迁移

### 6.1 Hive 迁移

```dart
class HiveMigrationService {
  static Future<void> migrate() async {
    final box = Hive.box('app_info');
    final currentVersion = box.get('db_version', defaultValue: 0) as int;
    const latestVersion = 3;

    for (var v = currentVersion; v < latestVersion; v++) {
      switch (v) {
        case 0:
          await _migrateV0ToV1();
          break;
        case 1:
          await _migrateV1ToV2();
          break;
        case 2:
          await _migrateV2ToV3();
          break;
      }
    }

    await box.put('db_version', latestVersion);
  }

  static Future<void> _migrateV0ToV1() async {
    // 示例：添加新字段
    final medicineBox = Hive.box('medicines');
    for (final key in medicineBox.keys) {
      final medicine = medicineBox.get(key);
      if (medicine != null) {
        medicine.isPending = false;
        await medicine.save();
      }
    }
  }
}
```

## 7. 性能优化

### 7.1 查询优化

```dart
// 使用索引（Hive 不支持索引，用 Map 手动维护）
class MedicineIndex {
  final Map<String, String> _nameToId = {};

  void build(List<Medicine> medicines) {
    _nameToId.clear();
    for (final m in medicines) {
      _nameToId[m.name.toLowerCase()] = m.id;
    }
  }

  String? findByName(String name) => _nameToId[name.toLowerCase()];
}
```

### 7.2 批量操作

```dart
Future<void> batchUpdateMedicines(List<Medicine> medicines) async {
  final box = HiveService.medicines;
  final Map<String, Medicine> entries = {};
  for (final m in medicines) {
    entries[m.id] = m;
  }
  await box.putAll(entries);
}
```

## 8. 本地存储检查清单

- [ ] Hive 初始化完成
- [ ] 所有 Model 有 Adapter
- [ ] 敏感数据加密存储
- [ ] Token 存储在 Keychain/Keystore
- [ ] 缓存有 TTL 过期机制
- [ ] 图片缓存有大小限制
- [ ] 缓存自动清理
- [ ] 数据版本管理
- [ ] 数据库迁移脚本
- [ ] 离线数据可访问
- [ ] 同步后更新缓存
- [ ] 登出清除用户数据
- [ ] 批量操作优化

---

*本地存储是 APP 离线能力的基础。快速、安全、可控的本地存储，让用户随时随地都能使用。*
