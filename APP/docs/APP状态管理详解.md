# APP状态管理详解

> 本文档是家健镜 APP 状态管理的完整设计说明，覆盖状态分层、Provider 架构、状态持久化、状态同步、性能优化。面向移动端开发者，作为状态管理实现的权威依据。

## 1. 状态管理概述

### 1.1 设计目标

1. **可预测**：状态变更可追溯，调试友好
2. **高性能**：避免不必要的重建和重绘
3. **可持久化**：关键状态离线可用
4. **可同步**：多端状态自动同步
5. **可测试**：状态逻辑可单元测试

### 1.2 状态分层

| 层级 | 说明 | 存储 | 示例 |
| --- | --- | --- | --- |
| 全局状态 | 跨页面共享 | Provider + 内存 | 用户信息、家庭信息、主题 |
| 页面状态 | 单页面内 | StatefulWidget | 表单输入、筛选条件 |
| 临时状态 | 局部组件 | 组件内变量 | 动画状态、展开/收起 |
| 持久状态 | 跨会话保留 | SharedPreferences / Hive | 登录态、用户偏好 |
| 服务端状态 | 服务端为权威源 | 服务器数据库 | 药品列表、健康事件 |

### 1.3 技术选型

- **状态管理**：Provider（官方推荐，轻量）
- **路由**：Navigator 2.0 / go_router
- **本地存储**：SharedPreferences（简单键值）+ Hive（结构化数据）
- **网络缓存**：dio_cache_interceptor

## 2. Provider 架构

### 2.1 Provider 层级

```
MyApp
├── MultiProvider
│   ├── ChangeNotifierProvider<AuthProvider>
│   ├── ChangeNotifierProvider<HouseholdProvider>
│   ├── ChangeNotifierProvider<MemberProvider>
│   ├── ChangeNotifierProvider<MedicineProvider>
│   ├── ChangeNotifierProvider<VitalProvider>
│   ├── ChangeNotifierProvider<RiskProvider>
│   ├── ChangeNotifierProvider<ChatProvider>
│   ├── ChangeNotifierProvider<VisionProvider>
│   ├── ChangeNotifierProvider<SyncProvider>
│   └── ChangeNotifierProvider<ThemeProvider>
└── MaterialApp
```

### 2.2 基础 Provider

```dart
abstract class BaseProvider extends ChangeNotifier {
  bool _isLoading = false;
  String? _error;
  bool _isDisposed = false;

  bool get isLoading => _isLoading;
  String? get error => _error;
  bool get hasError => _error != null;

  @protected
  void setLoading(bool value) {
    if (_isDisposed) return;
    _isLoading = value;
    notifyListeners();
  }

  @protected
  void setError(String? error) {
    if (_isDisposed) return;
    _error = error;
    notifyListeners();
  }

  @protected
  Future<T> safeExecute<T>(
    Future<T> Function() action, {
    String? errorMessage,
  }) async {
    setLoading(true);
    setError(null);
    try {
      return await action();
    } catch (e) {
      setError(errorMessage ?? e.toString());
      rethrow;
    } finally {
      setLoading(false);
    }
  }

  @override
  void dispose() {
    _isDisposed = true;
    super.dispose();
  }
}
```

### 2.3 AuthProvider

```dart
class AuthProvider extends BaseProvider {
  final AuthRepository _authRepository;
  final LocalStorageService _localStorage;

  User? _currentUser;
  String? _accessToken;
  String? _refreshToken;

  User? get currentUser => _currentUser;
  bool get isLoggedIn => _accessToken != null;
  String? get accessToken => _accessToken;

  AuthProvider(this._authRepository, this._localStorage);

  Future<void> init() async {
    _accessToken = await _localStorage.getAccessToken();
    _refreshToken = await _localStorage.getRefreshToken();
    if (_accessToken != null) {
      await _loadCurrentUser();
    }
    notifyListeners();
  }

  Future<void> login(String phone, String password) async {
    final result = await safeExecute(
      () => _authRepository.login(phone, password),
      errorMessage: "登录失败，请检查手机号和密码",
    );
    _accessToken = result.accessToken;
    _refreshToken = result.refreshToken;
    await _localStorage.saveTokens(result.accessToken, result.refreshToken);
    await _loadCurrentUser();
  }

  Future<void> logout() async {
    await _authRepository.logout();
    _accessToken = null;
    _refreshToken = null;
    _currentUser = null;
    await _localStorage.clearTokens();
    notifyListeners();
  }

  Future<void> _loadCurrentUser() async {
    try {
      _currentUser = await _authRepository.getCurrentUser();
    } catch (e) {
      // Token 可能过期，尝试刷新
      await _refreshTokenIfNeeded();
    }
  }

  Future<void> _refreshTokenIfNeeded() async {
    if (_refreshToken == null) return;
    try {
      final result = await _authRepository.refreshToken(_refreshToken!);
      _accessToken = result.accessToken;
      await _localStorage.saveAccessToken(result.accessToken);
    } catch (e) {
      await logout();
    }
  }
}
```

### 2.4 MedicineProvider

```dart
class MedicineProvider extends BaseProvider {
  final MedicineRepository _medicineRepository;
  final SyncService _syncService;

  List<Medicine> _medicines = [];
  Map<String, Medicine> _medicineCache = {};

  List<Medicine> get medicines => List.unmodifiable(_medicines);
  List<Medicine> get activeMedicines =>
      _medicines.where((m) => m.isActive).toList();

  MedicineProvider(this._medicineRepository, this._syncService);

  Future<void> loadMedicines(String memberId) async {
    _medicines = await safeExecute(
      () => _medicineRepository.getMedicines(memberId),
    );
    _medicineCache = {for (var m in _medicines) m.id: m};
  }

  Future<Medicine> addMedicine({
    required String memberId,
    required String name,
    required String dosage,
    required String frequency,
  }) async {
    final medicine = await safeExecute(
      () => _medicineRepository.addMedicine(
        memberId: memberId,
        name: name,
        dosage: dosage,
        frequency: frequency,
      ),
    );
    _medicines.add(medicine);
    _medicineCache[medicine.id] = medicine;
    notifyListeners();
    return medicine;
  }

  Future<void> updateMedicine(Medicine medicine) async {
    final updated = await safeExecute(
      () => _medicineRepository.updateMedicine(medicine),
    );
    final index = _medicines.indexWhere((m) => m.id == updated.id);
    if (index != -1) {
      _medicines[index] = updated;
      _medicineCache[updated.id] = updated;
      notifyListeners();
    }
  }

  Future<void> deleteMedicine(String medicineId) async {
    await safeExecute(
      () => _medicineRepository.deleteMedicine(medicineId),
    );
    _medicines.removeWhere((m) => m.id == medicineId);
    _medicineCache.remove(medicineId);
    notifyListeners();
  }

  Medicine? getMedicineById(String id) => _medicineCache[id];

  List<Medicine> searchMedicine(String query) {
    if (query.isEmpty) return _medicines;
    return _medicines
        .where((m) => m.name.toLowerCase().contains(query.toLowerCase()))
        .toList();
  }
}
```

## 3. 状态持久化

### 3.1 LocalStorageService

```dart
class LocalStorageService {
  static const _keyAccessToken = 'access_token';
  static const _keyRefreshToken = 'refresh_token';
  static const _keyUserId = 'user_id';
  static const _keyThemeMode = 'theme_mode';
  static const _keyLanguage = 'language';

  final SharedPreferences _prefs;
  final Box _hiveBox;

  LocalStorageService(this._prefs, this._hiveBox);

  // Token 管理
  Future<void> saveTokens(String access, String refresh) async {
    await _prefs.setString(_keyAccessToken, access);
    await _prefs.setString(_keyRefreshToken, refresh);
  }

  String? getAccessToken() => _prefs.getString(_keyAccessToken);
  String? getRefreshToken() => _prefs.getString(_keyRefreshToken);

  Future<void> clearTokens() async {
    await _prefs.remove(_keyAccessToken);
    await _prefs.remove(_keyRefreshToken);
  }

  // 用户偏好
  Future<void> setThemeMode(ThemeMode mode) async {
    await _prefs.setString(_keyThemeMode, mode.name);
  }

  ThemeMode getThemeMode() {
    final name = _prefs.getString(_keyThemeMode);
    return ThemeMode.values.firstWhere(
      (m) => m.name == name,
      orElse: () => ThemeMode.system,
    );
  }

  // 结构化数据（Hive）
  Future<void> cacheMedicines(List<Medicine> medicines) async {
    await _hiveBox.put('medicines', medicines.map((m) => m.toJson()).toList());
  }

  List<Medicine> getCachedMedicines() {
    final data = _hiveBox.get('medicines');
    if (data == null) return [];
    return (data as List).map((e) => Medicine.fromJson(e)).toList();
  }
}
```

### 3.2 离线数据缓存策略

| 数据类型 | 缓存方式 | 有效期 | 同步策略 |
| --- | --- | --- | --- |
| 用户信息 | SharedPreferences | 永久 | 启动时刷新 |
| 药品列表 | Hive | 7 天 | 启动时 + 下拉刷新 |
| 健康事件 | Hive | 30 天 | 增量同步 |
| 风险列表 | Hive | 1 天 | 实时推送 + 定时刷新 |
| 聊天记录 | Hive | 永久 | 增量同步 |
| 图片缓存 | 文件系统 | 30 天 | LRU 淘汰 |

## 4. 状态同步

### 4.1 SyncProvider

```dart
class SyncProvider extends BaseProvider {
  final SyncService _syncService;
  final WebSocketService _wsService;

  DateTime? _lastSyncTime;
  SyncStatus _status = SyncStatus.idle;

  DateTime? get lastSyncTime => _lastSyncTime;
  SyncStatus get status => _status;
  bool get isSyncing => _status == SyncStatus.syncing;

  SyncProvider(this._syncService, this._wsService) {
    _wsService.onDataChanged = _onServerDataChanged;
  }

  Future<void> fullSync() async {
    if (_status == SyncStatus.syncing) return;
    _status = SyncStatus.syncing;
    notifyListeners();

    try {
      await _syncService.pullChanges();
      await _syncService.pushLocalChanges();
      _lastSyncTime = DateTime.now();
      _status = SyncStatus.idle;
    } catch (e) {
      _status = SyncStatus.failed;
      setError("同步失败：$e");
    } finally {
      notifyListeners();
    }
  }

  void _onServerDataChanged(String changeType) {
    // 服务端数据变更，触发增量同步
    Future.microtask(() => incrementalSync(changeType));
  }

  Future<void> incrementalSync(String changeType) async {
    // 根据变更类型拉取对应数据
    switch (changeType) {
      case 'medicine':
        await _medicineProvider?.refresh();
        break;
      case 'risk':
        await _riskProvider?.refresh();
        break;
      default:
        await fullSync();
    }
  }
}
```

### 4.2 乐观更新

```dart
Future<void> addMedicineOptimistic({
  required String memberId,
  required String name,
}) async {
  // 1. 乐观更新：先更新 UI
  final tempId = 'temp_${DateTime.now().millisecondsSinceEpoch}';
  final tempMedicine = Medicine(
    id: tempId,
    name: name,
    isPending: true,
  );
  _medicines.add(tempMedicine);
  notifyListeners();

  try {
    // 2. 实际请求
    final realMedicine = await _medicineRepository.addMedicine(
      memberId: memberId,
      name: name,
    );
    // 3. 替换临时数据
    final index = _medicines.indexWhere((m) => m.id == tempId);
    if (index != -1) {
      _medicines[index] = realMedicine;
      notifyListeners();
    }
  } catch (e) {
    // 4. 回滚
    _medicines.removeWhere((m) => m.id == tempId);
    notifyListeners();
    rethrow;
  }
}
```

## 5. 性能优化

### 5.1 Selector 精准重建

```dart
// 不好：整个页面重建
Consumer<MedicineProvider>(
  builder: (context, provider, child) {
    return Text(provider.medicines.length.toString());
  },
)

// 好：只监听需要的字段
Selector<MedicineProvider, int>(
  selector: (context, provider) => provider.medicines.length,
  builder: (context, count, child) {
    return Text(count.toString());
  },
)
```

### 5.2 列表性能优化

```dart
ListView.builder(
  itemCount: medicines.length,
  itemBuilder: (context, index) {
    return MedicineCard(
      key: ValueKey(medicines[index].id),
      medicine: medicines[index],
    );
  },
)
```

### 5.3 防抖与节流

```dart
class Debouncer {
  final Duration delay;
  Timer? _timer;

  Debouncer({this.delay = const Duration(milliseconds: 300)});

  void run(VoidCallback action) {
    _timer?.cancel();
    _timer = Timer(delay, action);
  }

  void dispose() {
    _timer?.cancel();
  }
}

// 搜索防抖
final _debouncer = Debouncer();
void onSearchChanged(String query) {
  _debouncer.run(() => searchMedicine(query));
}
```

## 6. 状态调试

### 6.1 状态日志

```dart
class DebugProviderObserver extends ProviderObserver {
  @override
  void didUpdateProvider(
    ProviderBase provider,
    Object? previousValue,
    Object? newValue,
    ProviderContainer container,
  ) {
    debugPrint('{"provider": "${provider.name ?? provider.runtimeType}", "newValue": "$newValue"}');
  }
}
```

## 7. 状态管理检查清单

- [ ] 全局状态使用 Provider
- [ ] 页面状态使用 StatefulWidget
- [ ] 关键状态持久化
- [ ] 登录态安全存储
- [ ] 离线数据可访问
- [ ] 多端状态自动同步
- [ ] 乐观更新有回滚
- [ ] 使用 Selector 减少重建
- [ ] 列表使用 ValueKey
- [ ] 搜索输入有防抖
- [ ] 状态变更有日志
- [ ] Provider 正确 dispose

---

*状态管理是 APP 体验的基石。可预测、高性能、可同步的状态，让用户操作流畅无卡顿。*
