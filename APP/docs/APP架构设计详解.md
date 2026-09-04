# APP架构设计详解

> 本文档是家健镜系统 APP 架构设计的完整说明，覆盖分层架构、模块化设计、依赖注入、数据流。

## 1. 概述

### 1.1 架构目标

1. 可维护性：代码结构清晰，易于修改
2. 可测试性：各层可独立测试
3. 可扩展性：支持功能模块插拔
4. 性能：启动快、响应快
5. 稳定性：崩溃率 < 0.1%

### 1.2 架构分层

| 层级 | 职责 | 关键组件 |
| --- | --- | --- |
| 表现层 | UI 渲染、用户交互 | Page、Widget、ViewModel |
| 领域层 | 业务逻辑、领域模型 | Entity、UseCase、Repository |
| 数据层 | 数据存取、网络请求 | ApiService、Dao、DataSource |
| 基础设施层 | 工具、配置、平台通道 | Utils、Config、PlatformChannel |

## 2. 分层架构

### 2.1 目录结构

```
lib/
├── main.dart
├── app/
│   ├── app.dart
│   ├── routes.dart
│   └── theme.dart
├── core/
│   ├── constants/
│   ├── utils/
│   ├── errors/
│   └── network/
├── data/
│   ├── models/
│   ├── datasources/
│   ├── repositories/
│   └── mappers/
├── domain/
│   ├── entities/
│   ├── repositories/
│   └── usecases/
├── presentation/
│   ├── pages/
│   ├── widgets/
│   ├── viewmodels/
│   └── blocs/
└── injection.dart
```

### 2.2 表现层

```dart
// ViewModel
class MedicineViewModel extends ChangeNotifier {
  final GetMedicinesUseCase _getMedicines;
  final AddMedicineUseCase _addMedicine;

  MedicineViewModel(this._getMedicines, this._addMedicine);

  List<Medicine> _medicines = [];
  List<Medicine> get medicines => _medicines;

  bool _isLoading = false;
  bool get isLoading => _isLoading;

  Future<void> loadMedicines(String memberId) async {
    _isLoading = true;
    notifyListeners();

    final result = await _getMedicines(memberId);
    result.fold(
      (failure) => _error = failure,
      (medicines) => _medicines = medicines,
    );

    _isLoading = false;
    notifyListeners();
  }
}
```

### 2.3 领域层

```dart
// Entity
class Medicine {
  final String id;
  final String name;
  final String dosage;
  final String frequency;
  final DateTime startDate;
  final DateTime? endDate;

  Medicine({
    required this.id,
    required this.name,
    required this.dosage,
    required this.frequency,
    required this.startDate,
    this.endDate,
  });
}

// UseCase
class GetMedicinesUseCase {
  final MedicineRepository _repository;

  GetMedicinesUseCase(this._repository);

  Future<Either<Failure, List<Medicine>>> call(String memberId) {
    return _repository.getMedicines(memberId);
  }
}
```

### 2.4 数据层

```dart
// Repository 实现
class MedicineRepositoryImpl implements MedicineRepository {
  final MedicineRemoteDataSource _remote;
  final MedicineLocalDataSource _local;
  final NetworkInfo _networkInfo;

  MedicineRepositoryImpl(this._remote, this._local, this._networkInfo);

  @override
  Future<Either<Failure, List<Medicine>>> getMedicines(String memberId) async {
    if (await _networkInfo.isConnected) {
      try {
        final remoteMedicines = await _remote.getMedicines(memberId);
        await _local.cacheMedicines(remoteMedicines);
        return Right(remoteMedicines.map((e) => e.toEntity()).toList());
      } on ServerException {
        return Left(ServerFailure());
      }
    } else {
      try {
        final localMedicines = await _local.getCachedMedicines();
        return Right(localMedicines.map((e) => e.toEntity()).toList());
      } on CacheException {
        return Left(CacheFailure());
      }
    }
  }
}
```

## 3. 状态管理

### 3.1 Provider + ChangeNotifier

```dart
// 注册
void main() {
  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => MedicineViewModel()),
        ChangeNotifierProvider(create: (_) => HealthDataViewModel()),
        Provider(create: (_) => ApiService()),
      ],
      child: MyApp(),
    ),
  );
}

// 使用
class MedicinePage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Consumer<MedicineViewModel>(
        builder: (context, viewModel, child) {
          if (viewModel.isLoading) {
            return Center(child: CircularProgressIndicator());
          }
          return ListView.builder(
            itemCount: viewModel.medicines.length,
            itemBuilder: (context, index) {
              return MedicineCard(medicine: viewModel.medicines[index]);
            },
          );
        },
      ),
    );
  }
}
```

### 3.2 Bloc 模式

```dart
// Event
abstract class MedicineEvent {}
class LoadMedicines extends MedicineEvent {
  final String memberId;
  LoadMedicines(this.memberId);
}

// State
abstract class MedicineState {}
class MedicineInitial extends MedicineState {}
class MedicineLoading extends MedicineState {}
class MedicineLoaded extends MedicineState {
  final List<Medicine> medicines;
  MedicineLoaded(this.medicines);
}
class MedicineError extends MedicineState {
  final String message;
  MedicineError(this.message);
}

// Bloc
class MedicineBloc extends Bloc<MedicineEvent, MedicineState> {
  final GetMedicinesUseCase _getMedicines;

  MedicineBloc(this._getMedicines) : super(MedicineInitial()) {
    on<LoadMedicines>(_onLoadMedicines);
  }

  Future<void> _onLoadMedicines(
    LoadMedicines event,
    Emitter<MedicineState> emit,
  ) async {
    emit(MedicineLoading());
    final result = await _getMedicines(event.memberId);
    result.fold(
      (failure) => emit(MedicineError(failure.message)),
      (medicines) => emit(MedicineLoaded(medicines)),
    );
  }
}
```

## 4. 依赖注入

### 4.1 get_it 注册

```dart
final sl = GetIt.instance;

Future<void> init() async {
  // 外部依赖
  sl.registerLazySingleton(() => http.Client());
  sl.registerLazySingleton(() => InternetConnectionChecker());

  // 核心
  sl.registerLazySingleton<NetworkInfo>(() => NetworkInfoImpl(sl()));

  // 数据层
  sl.registerLazySingleton<MedicineRemoteDataSource>(
    () => MedicineRemoteDataSourceImpl(client: sl()),
  );
  sl.registerLazySingleton<MedicineLocalDataSource>(
    () => MedicineLocalDataSourceImpl(sharedPreferences: sl()),
  );
  sl.registerLazySingleton<MedicineRepository>(
    () => MedicineRepositoryImpl(
      remote: sl(),
      local: sl(),
      networkInfo: sl(),
    ),
  );

  // 领域层
  sl.registerLazySingleton(() => GetMedicinesUseCase(sl()));
  sl.registerLazySingleton(() => AddMedicineUseCase(sl()));

  // 表现层
  sl.registerFactory(() => MedicineViewModel(sl(), sl()));
}
```

## 5. 模块化设计

### 5.1 功能模块划分

| 模块 | 功能 | 依赖 |
| --- | --- | --- |
| auth | 登录注册、身份认证 | core, network |
| medicine | 用药管理、提醒 | core, database |
| health | 健康数据、体征记录 | core, database |
| family | 家庭成员管理 | core, network |
| profile | 个人中心、设置 | core |
| home | 首页、导航 | 所有模块 |

### 5.2 模块间通信

```dart
// 事件总线
class EventBus {
  static final EventBus _instance = EventBus._internal();
  factory EventBus() => _instance;
  EventBus._internal();

  final _streamController = StreamController<AppEvent>.broadcast();

  Stream<T> on<T extends AppEvent>() {
    return _streamController.stream.where((event) => event is T).cast<T>();
  }

  void fire(AppEvent event) {
    _streamController.add(event);
  }

  void dispose() {
    _streamController.close();
  }
}

// 事件定义
class MedicineAddedEvent extends AppEvent {
  final Medicine medicine;
  MedicineAddedEvent(this.medicine);
}

// 发送
EventBus().fire(MedicineAddedEvent(medicine));

// 监听
EventBus().on<MedicineAddedEvent>().listen((event) {
  print('新增药品: ${event.medicine.name}');
});
```

## 6. 数据流

### 6.1 单向数据流

```
UI → ViewModel → UseCase → Repository → DataSource
 ↑                                                    ↓
 ←────────────── State ←──────────────────────────────
```

### 6.2 数据同步策略

```dart
class SyncManager {
  final MedicineRepository _repository;
  final SyncLogDao _syncLogDao;

  Future<void> syncAll() async {
    await _syncMedicines();
    await _syncHealthRecords();
    await _syncFamilyMembers();
  }

  Future<void> _syncMedicines() async {
    final lastSync = await _syncLogDao.getLastSyncTime('medicines');
    final result = await _repository.syncMedicines(since: lastSync);
    result.fold(
      (failure) => print('同步失败: $failure'),
      (_) => _syncLogDao.updateSyncTime('medicines', DateTime.now()),
    );
  }
}
```

## 7. 架构检查清单

- [ ] 分层架构
- [ ] 目录结构
- [ ] 表现层
- [ ] 领域层
- [ ] 数据层
- [ ] 状态管理
- [ ] 依赖注入
- [ ] 模块化设计
- [ ] 模块间通信
- [ ] 单向数据流
- [ ] 数据同步
- [ ] 错误处理

---

*清晰的架构是可维护性的基石。分层、模块化、依赖注入，让 APP 健康成长。*
