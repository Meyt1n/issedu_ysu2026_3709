# APP状态管理与架构设计

> 本文档是家健镜系统 APP 状态管理与架构的完整设计说明，覆盖状态管理方案、架构分层、依赖注入、数据流、测试策略。

## 1. 概述

### 1.1 设计目标

1. 状态可预测
2. 代码可维护
3. 易于测试
4. 性能优化
5. 团队协作

### 1.2 架构选型

| 方案 | 优点 | 缺点 | 适用场景 |
| --- | --- | --- | --- |
| Provider | 简单、轻量 | 大项目状态分散 | 中小项目 |
| Bloc | 可预测、易测试 | 代码量大 | 中大型项目 |
| Riverpod | 编译安全、灵活 | 学习曲线 | 中大型项目 |
| GetX | 功能全、简单 | 侵入性强 | 快速开发 |
| Redux | 单向数据流 | 样板代码多 | 大型项目 |

## 2. 架构分层

### 2.1 分层架构

```
┌─────────────────────────┐
│      Presentation       │  UI、Widget、Bloc
├─────────────────────────┤
│        Domain           │  实体、用例、仓库接口
├─────────────────────────┤
│        Data             │  仓库实现、数据源、DTO
├─────────────────────────┤
│      Infrastructure     │  网络、数据库、第三方
└─────────────────────────┘
```

### 2.2 各层职责

```dart
// Presentation 层
class MedicineBloc extends Bloc<MedicineEvent, MedicineState> {
  final GetMedicinesUseCase getMedicines;
  final AddMedicineUseCase addMedicine;

  MedicineBloc({required this.getMedicines, required this.addMedicine})
      : super(MedicineInitial()) {
    on<LoadMedicines>(_onLoadMedicines);
    on<AddMedicine>(_onAddMedicine);
  }
}

// Domain 层
abstract class MedicineRepository {
  Future<List<Medicine>> getMedicines();
  Future<void> addMedicine(Medicine medicine);
}

class GetMedicinesUseCase {
  final MedicineRepository repository;
  GetMedicinesUseCase(this.repository);
  Future<List<Medicine>> call() => repository.getMedicines();
}

// Data 层
class MedicineRepositoryImpl implements MedicineRepository {
  final MedicineRemoteDataSource remote;
  final MedicineLocalDataSource local;

  MedicineRepositoryImpl({required this.remote, required this.local});

  @override
  Future<List<Medicine>> getMedicines() async {
    try {
      final remoteData = await remote.getMedicines();
      return remoteData.map((dto) => dto.toDomain()).toList();
    } catch (e) {
      final localData = await local.getCachedMedicines();
      return localData.map((dto) => dto.toDomain()).toList();
    }
  }
}
```

## 3. 状态管理

### 3.1 Bloc 模式

```dart
// Event
abstract class MedicineEvent extends Equatable {
  const MedicineEvent();
  @override
  List<Object> get props => [];
}

class LoadMedicines extends MedicineEvent {}

class AddMedicine extends MedicineEvent {
  final Medicine medicine;
  const AddMedicine(this.medicine);
  @override
  List<Object> get props => [medicine];
}

// State
abstract class MedicineState extends Equatable {
  const MedicineState();
  @override
  List<Object> get props => [];
}

class MedicineInitial extends MedicineState {}

class MedicineLoading extends MedicineState {}

class MedicineLoaded extends MedicineState {
  final List<Medicine> medicines;
  const MedicineLoaded(this.medicines);
  @override
  List<Object> get props => [medicines];
}

class MedicineError extends MedicineState {
  final String message;
  const MedicineError(this.message);
  @override
  List<Object> get props => [message];
}

// Bloc
class MedicineBloc extends Bloc<MedicineEvent, MedicineState> {
  final MedicineRepository repository;

  MedicineBloc({required this.repository}) : super(MedicineInitial()) {
    on<LoadMedicines>(_onLoad);
    on<AddMedicine>(_onAdd);
  }

  Future<void> _onLoad(LoadMedicines event, Emitter<MedicineState> emit) async {
    emit(MedicineLoading());
    try {
      final medicines = await repository.getMedicines();
      emit(MedicineLoaded(medicines));
    } catch (e) {
      emit(MedicineError(e.toString()));
    }
  }

  Future<void> _onAdd(AddMedicine event, Emitter<MedicineState> emit) async {
    try {
      await repository.addMedicine(event.medicine);
      add(LoadMedicines());
    } catch (e) {
      emit(MedicineError(e.toString()));
    }
  }
}
```

### 3.2 Cubit 简化版

```dart
class MedicineCubit extends Cubit<MedicineState> {
  final MedicineRepository repository;

  MedicineCubit({required this.repository}) : super(MedicineInitial());

  Future<void> loadMedicines() async {
    emit(MedicineLoading());
    try {
      final medicines = await repository.getMedicines();
      emit(MedicineLoaded(medicines));
    } catch (e) {
      emit(MedicineError(e.toString()));
    }
  }

  Future<void> addMedicine(Medicine medicine) async {
    try {
      await repository.addMedicine(medicine);
      loadMedicines();
    } catch (e) {
      emit(MedicineError(e.toString()));
    }
  }
}
```

### 3.3 Riverpod

```dart
final medicineRepositoryProvider = Provider<MedicineRepository>((ref) {
  return MedicineRepositoryImpl(
    remote: MedicineRemoteDataSource(),
    local: MedicineLocalDataSource(),
  );
});

final medicinesProvider = FutureProvider<List<Medicine>>((ref) async {
  final repository = ref.watch(medicineRepositoryProvider);
  return repository.getMedicines();
});

final medicineControllerProvider =
    StateNotifierProvider<MedicineController, AsyncValue<List<Medicine>>>((ref) {
  return MedicineController(ref.watch(medicineRepositoryProvider));
});

class MedicineController extends StateNotifier<AsyncValue<List<Medicine>>> {
  final MedicineRepository repository;

  MedicineController(this.repository) : super(const AsyncValue.loading()) {
    loadMedicines();
  }

  Future<void> loadMedicines() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => repository.getMedicines());
  }

  Future<void> addMedicine(Medicine medicine) async {
    await repository.addMedicine(medicine);
    loadMedicines();
  }
}
```

## 4. 依赖注入

### 4.1 get_it

```dart
final getIt = GetIt.instance;

void setupDependencies() {
  // 数据源
  getIt.registerLazySingleton<MedicineRemoteDataSource>(
    () => MedicineRemoteDataSourceImpl(apiClient: getIt()),
  );
  getIt.registerLazySingleton<MedicineLocalDataSource>(
    () => MedicineLocalDataSourceImpl(database: getIt()),
  );

  // 仓库
  getIt.registerLazySingleton<MedicineRepository>(
    () => MedicineRepositoryImpl(remote: getIt(), local: getIt()),
  );

  // 用例
  getIt.registerFactory(() => GetMedicinesUseCase(getIt()));
  getIt.registerFactory(() => AddMedicineUseCase(getIt()));

  // Bloc
  getIt.registerFactory(() => MedicineBloc(getMedicines: getIt(), addMedicine: getIt()));
}
```

### 4.2 Provider 注入

```dart
void main() {
  runApp(
    MultiProvider(
      providers: [
        Provider<ApiClient>(create: (_) => ApiClient()),
        Provider<MedicineRepository>(create: (_) => MedicineRepositoryImpl()),
        BlocProvider<MedicineBloc>(
          create: (context) => MedicineBloc(repository: context.read()),
        ),
      ],
      child: MyApp(),
    ),
  );
}
```

## 5. 数据流

### 5.1 单向数据流

```
用户操作 → Event → Bloc → Repository → DataSource
                ↑                        ↓
              State ←  Domain Model ← DTO
```

### 5.2 响应式数据流

```dart
class HealthDataService {
  final StreamController<HealthData> _controller = StreamController.broadcast();
  Stream<HealthData> get healthDataStream => _controller.stream;

  void updateHealthData(HealthData data) {
    _controller.add(data);
  }

  void dispose() {
    _controller.close();
  }
}

// 使用
StreamBuilder<HealthData>(
  stream: healthDataService.healthDataStream,
  builder: (context, snapshot) {
    if (snapshot.hasData) {
      return HealthDataWidget(data: snapshot.data!);
    }
    return CircularProgressIndicator();
  },
)
```

## 6. 状态持久化

### 6.1 Hydrated Bloc

```dart
class MedicineBloc extends HydratedBloc<MedicineEvent, MedicineState> {
  MedicineBloc() : super(MedicineInitial());

  @override
  MedicineState? fromJson(Map<String, dynamic> json) {
    if (json['medicines'] != null) {
      return MedicineLoaded(
        (json['medicines'] as List).map((e) => Medicine.fromJson(e)).toList(),
      );
    }
    return null;
  }

  @override
  Map<String, dynamic>? toJson(MedicineState state) {
    if (state is MedicineLoaded) {
      return {'medicines': state.medicines.map((e) => e.toJson()).toList()};
    }
    return null;
  }
}
```

## 7. 测试策略

### 7.1 Bloc 测试

```dart
void main() {
  group('MedicineBloc', () {
    late MockMedicineRepository repository;
    late MedicineBloc bloc;

    setUp(() {
      repository = MockMedicineRepository();
      bloc = MedicineBloc(repository: repository);
    });

    test('initial state is MedicineInitial', () {
      expect(bloc.state, MedicineInitial());
    });

    blocTest<MedicineBloc, MedicineState>(
      'emits [Loading, Loaded] when LoadMedicines succeeds',
      build: () {
        when(repository.getMedicines()).thenAnswer((_) async => [testMedicine]);
        return bloc;
      },
      act: (bloc) => bloc.add(LoadMedicines()),
      expect: () => [
        MedicineLoading(),
        MedicineLoaded([testMedicine]),
      ],
    );
  });
}
```

## 8. 状态管理检查清单

- [ ] 架构分层
- [ ] Bloc 模式
- [ ] Cubit 简化
- [ ] Riverpod
- [ ] 依赖注入
- [ ] 单向数据流
- [ ] 响应式流
- [ ] 状态持久化
- [ ] Bloc 测试
- [ ] 错误处理
- [ ] 性能优化
- [ ] 代码规范

---

*清晰的状态管理是 APP 稳定的基石。分层架构、单向数据流、可预测状态，让复杂应用井然有序。*
