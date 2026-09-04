# APP离线使用与数据同步设计

> 本文档是家健镜系统 APP 离线使用与数据同步的完整设计说明，覆盖离线缓存、冲突解决、同步策略、数据一致性。

## 1. 概述

### 1.1 设计目标

1. 离线可用：无网络时核心功能可用
2. 自动同步：联网后自动同步数据
3. 冲突解决：多端修改智能合并
4. 数据一致：最终一致性保障
5. 用户体验：同步过程无感知

### 1.2 离线功能范围

| 功能 | 离线可用 | 说明 |
| --- | --- | --- |
| 查看药品列表 | 是 | 本地缓存 |
| 添加药品 | 是 | 本地暂存，联网后同步 |
| 编辑药品 | 是 | 本地暂存，联网后同步 |
| 服药记录 | 是 | 本地暂存，联网后同步 |
| 查看体征记录 | 是 | 本地缓存 |
| 记录体征 | 是 | 本地暂存，联网后同步 |
| 健康助手对话 | 否 | 需要在线 |
| 视觉识别 | 否 | 需要在线 |
| 数据同步 | - | 联网后自动 |

## 2. 本地存储

### 2.1 数据库设计

```dart
class AppDatabase {
  static Database? _db;

  static Future<Database> getInstance() async {
    if (_db != null) return _db!;

    _db = await openDatabase(
      'homecare_offline.db',
      version: 1,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE medicines (
            id TEXT PRIMARY KEY,
            name TEXT,
            dosage TEXT,
            frequency TEXT,
            version INTEGER,
            updated_at TEXT,
            sync_status TEXT,
            pending_delete INTEGER DEFAULT 0
          )
        ''');

        await db.execute('''
          CREATE TABLE medication_records (
            id TEXT PRIMARY KEY,
            medicine_id TEXT,
            scheduled_time TEXT,
            taken_time TEXT,
            status TEXT,
            version INTEGER,
            sync_status TEXT
          )
        ''');

        await db.execute('''
          CREATE TABLE sync_queue (
            id TEXT PRIMARY KEY,
            entity_type TEXT,
            entity_id TEXT,
            operation TEXT,
            data TEXT,
            timestamp TEXT,
            retry_count INTEGER DEFAULT 0
          )
        ''');
      },
    );
    return _db!;
  }
}
```

### 2.2 本地数据操作

```dart
class MedicineLocalRepository {
  final Database _db;

  MedicineLocalRepository(this._db);

  Future<List<Medicine>> getAll() async {
    final maps = await _db.query(
      'medicines',
      where: 'pending_delete = 0',
      orderBy: 'name',
    );
    return maps.map((m) => Medicine.fromMap(m)).toList();
  }

  Future<void> upsert(Medicine medicine, {String syncStatus = 'pending'}) async {
    await _db.insert(
      'medicines',
      {
        ...medicine.toMap(),
        'sync_status': syncStatus,
        'updated_at': DateTime.now().toIso8601String(),
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> markDeleted(String id) async {
    await _db.update(
      'medicines',
      {'pending_delete': 1, 'sync_status': 'pending'},
      where: 'id = ?',
      whereArgs: [id],
    );
  }
}
```

## 3. 同步队列

### 3.1 队列管理

```dart
class SyncQueue {
  final Database _db;

  SyncQueue(this._db);

  Future<void> enqueue({
    required String entityType,
    required String entityId,
    required String operation,
    required Map<String, dynamic> data,
  }) async {
    await _db.insert(
      'sync_queue',
      {
        'id': const Uuid().v4(),
        'entity_type': entityType,
        'entity_id': entityId,
        'operation': operation,
        'data': jsonEncode(data),
        'timestamp': DateTime.now().toIso8601String(),
        'retry_count': 0,
      },
    );
  }

  Future<List<SyncItem>> getPending() async {
    final maps = await _db.query(
      'sync_queue',
      orderBy: 'timestamp ASC',
      limit: 50,
    );
    return maps.map((m) => SyncItem.fromMap(m)).toList();
  }

  Future<void> remove(String id) async {
    await _db.delete('sync_queue', where: 'id = ?', whereArgs: [id]);
  }

  Future<void> incrementRetry(String id) async {
    await _db.rawUpdate(
      'UPDATE sync_queue SET retry_count = retry_count + 1 WHERE id = ?',
      [id],
    );
  }
}
```

### 3.2 同步执行

```dart
class SyncManager {
  final SyncQueue _queue;
  final ApiClient _api;
  bool _isSyncing = false;

  SyncManager(this._queue, this._api);

  Future<void> sync() async {
    if (_isSyncing) return;
    if (!await _isOnline()) return;

    _isSyncing = true;
    try {
      final items = await _queue.getPending();

      for (final item in items) {
        try {
          await _syncItem(item);
          await _queue.remove(item.id);
        } catch (e) {
          await _queue.incrementRetry(item.id);
          if (item.retryCount >= 5) {
            // 标记为失败，需要人工处理
            await _markFailed(item);
          }
        }
      }

      // 拉取服务端变更
      await _pullChanges();
    } finally {
      _isSyncing = false;
    }
  }

  Future<void> _syncItem(SyncItem item) async {
    switch (item.operation) {
      case 'create':
        await _api.create(item.entityType, item.data);
        break;
      case 'update':
        await _api.update(item.entityType, item.entityId, item.data);
        break;
      case 'delete':
        await _api.delete(item.entityType, item.entityId);
        break;
    }
  }
}
```

## 4. 冲突解决

### 4.1 冲突检测

```dart
class ConflictDetector {
  bool hasConflict(LocalData local, RemoteData remote) {
    // 版本号比较
    if (local.version > remote.version) {
      return false; // 本地更新，无冲突
    }
    if (local.version < remote.version) {
      return true; // 服务端更新，可能冲突
    }
    return false;
  }
}
```

### 4.2 冲突解决策略

```dart
class ConflictResolver {
  Future<ResolvedData> resolve(
    LocalData local,
    RemoteData remote,
  ) async {
    // 策略 1：最后修改胜出
    if (local.updatedAt.isAfter(remote.updatedAt)) {
      return ResolvedData(data: local.data, source: 'local');
    }

    // 策略 2：字段级合并
    final merged = _fieldLevelMerge(local.data, remote.data);
    return ResolvedData(data: merged, source: 'merged');
  }

  Map<String, dynamic> _fieldLevelMerge(
    Map<String, dynamic> local,
    Map<String, dynamic> remote,
  ) {
    final merged = Map<String, dynamic>.from(remote);
    local.forEach((key, value) {
      if (!remote.containsKey(key)) {
        merged[key] = value;
      }
    });
    return merged;
  }
}
```

## 5. 网络监听

### 5.1 连接状态

```dart
class ConnectivityService {
  final Connectivity _connectivity = Connectivity();
  final StreamController<bool> _controller = StreamController<bool>.broadcast();

  Stream<bool> get connectivityStream => _controller.stream;

  void init() {
    _connectivity.onConnectivityChanged.listen((result) {
      _controller.add(result != ConnectivityResult.none);
    });
  }

  Future<bool> isOnline() async {
    final result = await _connectivity.checkConnectivity();
    return result != ConnectivityResult.none;
  }
}
```

### 5.2 自动同步触发

```dart
class AutoSync {
  final SyncManager _syncManager;
  final ConnectivityService _connectivity;

  AutoSync(this._syncManager, this._connectivity) {
    _connectivity.connectivityStream.listen((online) {
      if (online) {
        _syncManager.sync();
      }
    });
  }
}
```

## 6. 离线检查清单

- [ ] 本地数据库
- [ ] 离线缓存
- [ ] 同步队列
- [ ] 自动同步
- [ ] 冲突检测
- [ ] 冲突解决
- [ ] 网络监听
- [ ] 数据一致性
- [ ] 同步状态显示
- [ ] 失败重试
- [ ] 手动同步
- [ ] 同步日志

---

*离线使用是移动应用的基本能力。可靠的离线支持和智能同步，让用户随时随地都能使用。*
