# APP测试策略与质量保障

> 本文档是家健镜系统 APP 测试策略与质量保障的完整设计说明，覆盖单元测试、Widget 测试、集成测试、性能测试、自动化测试。

## 1. 概述

### 1.1 质量目标

1. 单元测试覆盖率 > 80%
2. 核心流程自动化测试覆盖
3. 崩溃率 < 0.1%
4. 启动时间 < 2 秒
5. 内存泄漏为零

### 1.2 测试金字塔

| 层级 | 占比 | 工具 | 执行速度 |
| --- | --- | --- | --- |
| 单元测试 | 70% | flutter_test | 快 |
| Widget 测试 | 20% | flutter_test | 中 |
| 集成测试 | 10% | integration_test | 慢 |
| 手动测试 | 补充 | 人工 | 慢 |

## 2. 单元测试

### 2.1 工具配置

```yaml
dev_dependencies:
  flutter_test:
    sdk: flutter
  mockito: ^5.4.0
  build_runner: ^2.4.0
  flutter_lints: ^2.0.0
```

### 2.2 业务逻辑测试

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mockito/mockito.dart';

class MockMedicineRepository extends Mock implements MedicineRepository {}

void main() {
  group('MedicineBloc', () {
    late MockMedicineRepository repository;
    late MedicineBloc bloc;

    setUp(() {
      repository = MockMedicineRepository();
      bloc = MedicineBloc(repository: repository);
    });

    tearDown(() {
      bloc.close();
    });

    test('initial state is MedicineInitial', () {
      expect(bloc.state, isA<MedicineInitial>());
    });

    blocTest<MedicineBloc, MedicineState>(
      'emits [Loading, Loaded] when medicines load successfully',
      build: () {
        when(repository.getMedicines()).thenAnswer(
          (_) async => [Medicine(id: '1', name: '阿莫西林')],
        );
        return bloc;
      },
      act: (bloc) => bloc.add(LoadMedicines()),
      expect: () => [
        isA<MedicineLoading>(),
        isA<MedicineLoaded>().having(
          (s) => s.medicines.length,
          'medicines length',
          1,
        ),
      ],
    );

    blocTest<MedicineBloc, MedicineState>(
      'emits [Loading, Error] when repository throws',
      build: () {
        when(repository.getMedicines()).thenThrow(Exception('Network error'));
        return bloc;
      },
      act: (bloc) => bloc.add(LoadMedicines()),
      expect: () => [
        isA<MedicineLoading>(),
        isA<MedicineError>(),
      ],
    );
  });
}
```

### 2.3 工具类测试

```dart
void main() {
  group('DateUtils', () {
    test('formatDate returns correct format', () {
      final date = DateTime(2026, 9, 4);
      expect(DateUtils.formatDate(date), '2026-09-04');
    });

    test('isToday returns true for today', () {
      expect(DateUtils.isToday(DateTime.now()), isTrue);
    });

    test('daysBetween returns correct difference', () {
      final start = DateTime(2026, 9, 1);
      final end = DateTime(2026, 9, 4);
      expect(DateUtils.daysBetween(start, end), 3);
    });
  });

  group('Validator', () {
    test('empty email returns error', () {
      expect(Validator.validateEmail(''), '请输入邮箱');
    });

    test('invalid email returns error', () {
      expect(Validator.validateEmail('invalid'), '邮箱格式不正确');
    });

    test('valid email returns null', () {
      expect(Validator.validateEmail('test@example.com'), isNull);
    });
  });
}
```

## 3. Widget 测试

### 3.1 页面测试

```dart
void main() {
  group('MedicineListPage', () {
    testWidgets('shows loading indicator when loading', (tester) async {
      final mockBloc = MockMedicineBloc();
      when(mockBloc.state).thenReturn(MedicineLoading());
      when(mockBloc.stream).thenAnswer((_) => Stream.value(MedicineLoading()));

      await tester.pumpWidget(
        MaterialApp(
          home: BlocProvider<MedicineBloc>.value(
            value: mockBloc,
            child: MedicineListPage(),
          ),
        ),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('shows medicines when loaded', (tester) async {
      final medicines = [
        Medicine(id: '1', name: '阿莫西林', dosage: '500mg'),
        Medicine(id: '2', name: '布洛芬', dosage: '200mg'),
      ];
      final mockBloc = MockMedicineBloc();
      when(mockBloc.state).thenReturn(MedicineLoaded(medicines));
      when(mockBloc.stream).thenAnswer((_) => Stream.value(MedicineLoaded(medicines)));

      await tester.pumpWidget(
        MaterialApp(
          home: BlocProvider<MedicineBloc>.value(
            value: mockBloc,
            child: MedicineListPage(),
          ),
        ),
      );

      expect(find.text('阿莫西林'), findsOneWidget);
      expect(find.text('布洛芬'), findsOneWidget);
    });

    testWidgets('shows error message when error', (tester) async {
      final mockBloc = MockMedicineBloc();
      when(mockBloc.state).thenReturn(MedicineError('加载失败'));
      when(mockBloc.stream).thenAnswer((_) => Stream.value(MedicineError('加载失败')));

      await tester.pumpWidget(
        MaterialApp(
          home: BlocProvider<MedicineBloc>.value(
            value: mockBloc,
            child: MedicineListPage(),
          ),
        ),
      );

      expect(find.text('加载失败'), findsOneWidget);
    });
  });
}
```

### 3.2 交互测试

```dart
void main() {
  testWidgets('tapping add button navigates to add page', (tester) async {
    await tester.pumpWidget(MaterialApp(home: MedicineListPage()));

    final addButton = find.byKey(Key('add_medicine_button'));
    expect(addButton, findsOneWidget);

    await tester.tap(addButton);
    await tester.pumpAndSettle();

    expect(find.byType(AddMedicinePage), findsOneWidget);
  });

  testWidgets('tapping medicine opens detail', (tester) async {
    final medicines = [Medicine(id: '1', name: '阿莫西林')];
    await tester.pumpWidget(
      MaterialApp(home: MedicineListPage(medicines: medicines)),
    );

    await tester.tap(find.text('阿莫西林'));
    await tester.pumpAndSettle();

    expect(find.byType(MedicineDetailPage), findsOneWidget);
  });
}
```

## 4. 集成测试

### 4.1 端到端测试

```dart
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  group('App Integration Test', () {
    testWidgets('complete user flow', (tester) async {
      app.main();
      await tester.pumpAndSettle();

      // 登录
      await tester.enterText(find.byKey(Key('email_field')), 'test@example.com');
      await tester.enterText(find.byKey(Key('password_field')), 'password123');
      await tester.tap(find.byKey(Key('login_button')));
      await tester.pumpAndSettle(Duration(seconds: 3));

      // 验证进入首页
      expect(find.byType(HomePage), findsOneWidget);

      // 添加药品
      await tester.tap(find.byKey(Key('add_medicine_button')));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(Key('medicine_name')), '阿莫西林');
      await tester.enterText(find.byKey(Key('medicine_dosage')), '500mg');
      await tester.tap(find.byKey(Key('save_button')));
      await tester.pumpAndSettle();

      // 验证药品已添加
      expect(find.text('阿莫西林'), findsOneWidget);
    });
  });
}
```

## 5. 性能测试

### 5.1 启动性能

```dart
void main() {
  testWidgets('app starts within 2 seconds', (tester) async {
    final stopwatch = Stopwatch()..start();
    await tester.pumpWidget(app.MyApp());
    await tester.pumpAndSettle();
    stopwatch.stop();

    expect(stopwatch.elapsedMilliseconds, lessThan(2000));
  });
}
```

### 5.2 内存测试

```dart
void main() {
  testWidgets('no memory leak during navigation', (tester) async {
    final observer = TestNavigatorObserver();

    await tester.pumpWidget(MaterialApp(
      navigatorObservers: [observer],
      home: HomePage(),
    ));

    // 多次进出页面
    for (int i = 0; i < 10; i++) {
      await tester.tap(find.byKey(Key('medicine_item')));
      await tester.pumpAndSettle();
      await tester.pageBack();
      await tester.pumpAndSettle();
    }

    // 验证没有内存泄漏
    await tester.pump(Duration(seconds: 1));
  });
}
```

### 5.3 帧率测试

```dart
void main() {
  testWidgets('scrolling maintains 60fps', (tester) async {
    await tester.pumpWidget(MaterialApp(home: LongListPage()));
    await tester.pumpAndSettle();

    // 滚动列表
    await tester.fling(
      find.byType(ListView),
      Offset(0, -500),
      1000,
    );
    await tester.pumpAndSettle();
  });
}
```

## 6. 自动化测试

### 6.1 CI 集成

```yaml
name: Flutter Test
on:
  push:
    branches: [master]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Flutter
        uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.10.0'

      - name: Install dependencies
        run: flutter pub get

      - name: Run analyzer
        run: flutter analyze

      - name: Run tests
        run: flutter test --coverage

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: coverage/lcov.info
```

### 6.2 测试覆盖率

```bash
# 生成覆盖率报告
flutter test --coverage

# 查看覆盖率
genhtml coverage/lcov.info -o coverage/html

# 检查覆盖率阈值
flutter test --coverage
```

## 7. 手动测试

### 7.1 测试用例模板

```markdown
## 测试用例：用药提醒

### TC-001：正常提醒
- 前置条件：已添加药品并设置提醒
- 步骤：
  1. 到达提醒时间
  2. 查看通知
- 预期结果：收到用药提醒通知
- 实际结果：
- 状态：通过/失败

### TC-002：标记已服药
- 前置条件：收到用药提醒
- 步骤：
  1. 点击通知
  2. 点击"已服药"
- 预期结果：记录标记为已服药，通知消失
- 实际结果：
- 状态：通过/失败
```

## 8. 质量指标

### 8.1 质量看板

| 指标 | 目标 | 当前 | 状态 |
| --- | --- | --- | --- |
| 单元测试覆盖率 | > 80% | 82% | 达标 |
| 崩溃率 | < 0.1% | 0.05% | 达标 |
| ANR 率 | < 0.2% | 0.1% | 达标 |
| 启动时间 | < 2s | 1.5s | 达标 |
| 包体积 | < 50MB | 42MB | 达标 |
| 内存峰值 | < 200MB | 180MB | 达标 |

## 9. 测试检查清单

- [ ] 单元测试
- [ ] Bloc 测试
- [ ] 工具类测试
- [ ] Widget 测试
- [ ] 页面测试
- [ ] 交互测试
- [ ] 集成测试
- [ ] 启动性能
- [ ] 内存测试
- [ ] 帧率测试
- [ ] CI 集成
- [ ] 覆盖率报告

---

*完善的测试是质量的保障。单元测试、Widget 测试、集成测试，层层把关，让 APP 稳定可靠。*
