# APP本地数据库与持久化设计

> 本文档是家健镜系统 APP 本地数据库与持久化的完整设计说明，覆盖数据库选型、表结构设计、数据迁移、查询优化、数据同步。

## 1. 概述

### 1.1 设计目标

1. 查询响应 < 50ms
2. 支持离线使用
3. 数据安全加密
4. 自动数据同步
5. 易于迁移维护

### 1.2 存储方案

| 方案 | 适用场景 | 优点 | 缺点 |
| --- | --- | --- | --- |
| SQLite | 结构化数据 | 成熟、稳定 | SQL 复杂 |
| Hive | 键值存储 | 简单、快速 | 查询弱 |
| ObjectBox | 对象数据库 | 高性能 | 学习成本 |
| Realm | 移动端数据库 | 实时同步 | 体积大 |
| SharedPreferences | 配置存储 | 简单 | 仅键值 |

## 2. 数据库选型

### 2.1 Drift (SQLite)

```dart
import 'package:drift/drift.dart';
import 'package:drift/native.dart';

part 'database.g.dart';

class Medicines extends Table {
  TextColumn get id => text()();
  TextColumn get name => text()();
  TextColumn get dosage => text()();
  TextColumn get frequency => text()();
  TextColumn get notes => text().nullable()();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {id};
}

class MedicationLogs extends Table {
  TextColumn get id => text()();
  TextColumn get medicineId => text().references(Medicines, #id)();
  DateTimeColumn get scheduledTime => dateTime()();
  DateTimeColumn get takenTime => dateTime().nullable()();
  TextColumn get status => text().withDefault(const Constant('pending'))();
  BoolColumn get isMissed => boolean().withDefault(const Constant(false))();

  @override
  Set<Column> get primaryKey => {id};
}

class HealthRecords extends Table {
  TextColumn get id => text()();
  TextColumn get type => text()();
  RealColumn get value => real()();
  TextColumn get unit => text()();
  DateTimeColumn get measuredAt => dateTime()();
  TextColumn get note => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

@DriftDatabase(tables: [Medicines, MedicationLogs, HealthRecords])
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openConnection());

  @override
  int get schemaVersion => 3;

  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (Migrator m) => m.createAll(),
    onUpgrade: (Migrator m, int from, int to) async {
      if (from < 2) {
        await m.addColumn(medicines, medicines.notes);
      }
      if (from < 3) {
        await m.addColumn(medicationLogs, medicationLogs.isMissed);
      }
    },
  );
}
```

### 2.2 Hive

```dart
class MedicineBox extends HiveObject {
  @HiveField(0)
  late String id;

  @HiveField(1)
  late String name;

  @HiveField(2)
  late String dosage;

  @HiveField(3)
  late String frequency;

  @HiveField(4)
  DateTime? createdAt;
}

void initHive() async {
  await Hive.initFlutter();
  Hive.registerAdapter(MedicineBoxAdapter());
  await Hive.openBox<MedicineBox>('medicines');
  await Hive.openBox('settings');
  await Hive.openBox('cache');
}
```

## 3. 表结构设计

### 3.1 用户表

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    avatar TEXT,
    birth_date TEXT,
    gender TEXT,
    height REAL,
    weight REAL,
    blood_type TEXT,
    allergies TEXT,
    chronic_diseases TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_users_phone ON users(phone);
CREATE INDEX idx_users_email ON users(email);
```

### 3.2 药品表

```sql
CREATE TABLE medicines (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    generic_name TEXT,
    dosage TEXT NOT NULL,
    frequency TEXT NOT NULL,
    times TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    notes TEXT,
    color TEXT,
    icon TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX idx_medicines_user ON medicines(user_id);
CREATE INDEX idx_medicines_active ON medicines(is_active);
```

### 3.3 用药记录表

```sql
CREATE TABLE medication_logs (
    id TEXT PRIMARY KEY,
    medicine_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    taken_time TEXT,
    status TEXT DEFAULT 'pending',
    is_missed INTEGER DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (medicine_id) REFERENCES medicines(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX idx_logs_medicine ON medication_logs(medicine_id);
CREATE INDEX idx_logs_user_time ON medication_logs(user_id, scheduled_time);
CREATE INDEX idx_logs_status ON medication_logs(status);
```

### 3.4 健康记录表

```sql
CREATE TABLE health_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    source TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX idx_health_user_type ON health_records(user_id, type);
CREATE INDEX idx_health_measured ON health_records(measured_at);
```

## 4. 数据访问层

### 4.1 Repository 模式

```dart
class MedicineRepository {
  final AppDatabase _db;

  MedicineRepository(this._db);

  Future<List<Medicine>> getAllMedicines(String userId) async {
    return _db.select(_db.medicines)
      ..where((m) => m.userId.equals(userId) & m.isActive.equals(true))
      ..orderBy([(m) => OrderingTerm.asc(m.name)]);
  }

  Future<Medicine?> getMedicineById(String id) async {
    return (_db.select(_db.medicines)..where((m) => m.id.equals(id)))
        .getSingleOrNull();
  }

  Future<void> addMedicine(MedicinesCompanion medicine) async {
    await _db.into(_db.medicines).insert(medicine);
  }

  Future<void> updateMedicine(Medicine medicine) async {
    await _db.update(_db.medicines).replace(medicine);
  }

  Future<void> deleteMedicine(String id) async {
    await (_db.delete(_db.medicines)..where((m) => m.id.equals(id))).go();
  }

  Future<int> getMedicineCount(String userId) async {
    final count = _db.countAll();
    final query = _db.selectOnly(_db.medicines)
      ..addColumns([count])
      ..where(_db.medicines.userId.equals(userId));
    return (await query.getSingle()).read(count)!;
  }
}
```

### 4.2 查询优化

```dart
class HealthRecordRepository {
  final AppDatabase _db;

  Future<List<HealthRecord>> getRecentRecords(
    String userId,
    String type, {
    int limit = 30,
  }) async {
    return _db.select(_db.healthRecords)
      ..where((r) => r.userId.equals(userId) & r.type.equals(type))
      ..orderBy([(r) => OrderingTerm.desc(r.measuredAt)])
      ..limit(limit);
  }

  Future<Map<String, double>> getDailyAverages(
    String userId,
    String type,
    DateTime start,
    DateTime end,
  ) async {
    final query = _db.customSelect(
      '''
      SELECT DATE(measured_at) as date, AVG(value) as avg_value
      FROM health_records
      WHERE user_id = ? AND type = ? AND measured_at BETWEEN ? AND ?
      GROUP BY DATE(measured_at)
      ORDER BY date
      ''',
      variables: [
        Variable.withString(userId),
        Variable.withString(type),
        Variable.withString(start.toIso8601String()),
        Variable.withString(end.toIso8601String()),
      ],
    );

    final results = await query.get();
    return {
      for (final row in results)
        row.read<String>('date'): row.read<double>('avg_value'),
    };
  }
}
```

## 5. 数据迁移

### 5.1 版本迁移

```dart
@override
MigrationStrategy get migration => MigrationStrategy(
  onCreate: (Migrator m) async {
    await m.createAll();
  },
  onUpgrade: (Migrator m, int from, int to) async {
    if (from < 2) {
      await m.addColumn(medicines, medicines.notes);
      await m.addColumn(medicines, medicines.color);
    }
    if (from < 3) {
      await m.addColumn(medicationLogs, medicationLogs.isMissed);
      await m.createIndex('idx_logs_status', 'medication_logs', ['status']);
    }
    if (from < 4) {
      // 数据迁移：将旧格式转换为新格式
      final oldData = await customSelect('SELECT * FROM old_table').get();
      for (final row in oldData) {
        await into(medicines).insert(
          MedicinesCompanion.insert(
            id: const Value(''),
            name: Value(row.read('name')),
            dosage: Value(row.read('dosage')),
            frequency: Value(row.read('frequency')),
          ),
        );
      }
    }
  },
  beforeOpen: (details) async {
    if (details.wasCreated) {
      // 初始化默认数据
    }
  },
);
```

## 6. 数据加密

### 6.1 SQLCipher

```dart
import 'package:sqlcipher_flutter_libs/sqlcipher_flutter_libs.dart';

LazyDatabase _openEncryptedConnection() {
  return LazyDatabase(() async {
    final dbFolder = await getApplicationDocumentsDirectory();
    final file = File(p.join(dbFolder.path, 'app_encrypted.db'));
    return NativeDatabase(
      file,
      setup: (db) {
        db.execute("PRAGMA key = '${_getEncryptionKey()}'");
        db.execute("PRAGMA cipher_compatibility = 4");
      },
    );
  });
}

String _getEncryptionKey() {
  // 从安全存储获取密钥
  return FlutterSecureStorage().read(key: 'db_encryption_key').toString();
}
```

## 7. 数据同步

### 7.1 同步策略

```dart
class DataSyncService {
  final AppDatabase _db;
  final ApiClient _api;

  DataSyncService(this._db, this._api);

  Future<void> syncMedicines(String userId) async {
    // 1. 拉取远程数据
    final remoteMedicines = await _api.getMedicines(userId);

    // 2. 推送本地变更
    final localChanges = await _db.getUnsyncedMedicines();
    for (final medicine in localChanges) {
      await _api.upsertMedicine(medicine);
    }

    // 3. 合并数据
    for (final remote in remoteMedicines) {
      final local = await _db.getMedicineById(remote.id);
      if (local == null || remote.updatedAt.isAfter(local.updatedAt)) {
        await _db.upsertMedicine(remote);
      }
    }

    // 4. 标记已同步
    await _db.markAsSynced();
  }

  Future<void> autoSync() async {
    // 定时同步
    Timer.periodic(Duration(minutes: 5), (_) async {
      final userId = await _getCurrentUserId();
      if (userId != null) {
        await syncMedicines(userId);
      }
    });
  }
}
```

## 8. 本地数据库检查清单

- [ ] 数据库选型
- [ ] Drift 集成
- [ ] 用户表
- [ ] 药品表
- [ ] 用药记录表
- [ ] 健康记录表
- [ ] Repository 模式
- [ ] 查询优化
- [ ] 数据迁移
- [ ] 数据加密
- [ ] 数据同步
- [ ] 性能测试

---

*高效的本地存储是 APP 离线能力的保障。结构化设计、安全加密、智能同步，让数据随时随地可用。*
