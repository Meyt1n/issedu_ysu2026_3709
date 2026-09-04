# APP测试策略与用例设计

> 本文档是家健镜 APP 测试策略的完整设计说明，覆盖测试分层、单元测试、Widget测试、集成测试、测试工具、CI集成。面向移动端开发者和测试人员，作为测试实现的权威依据。

## 1. 测试策略概述

### 1.1 测试金字塔

```
        /E2E 测试\        <-- 少量，关键流程
       /集成测试\         <-- 中等，模块交互
      /Widget 测试\       <-- 较多，UI组件
     /单元测试\           <-- 大量，业务逻辑
    /____________\
```

### 1.2 测试覆盖率目标

| 层级 | 覆盖率目标 | 说明 |
| --- | --- | --- |
| 单元测试 | ≥80% | 核心业务逻辑 100% |
| Widget 测试 | ≥60% | 关键页面和组件 |
| 集成测试 | ≥40% | 核心用户流程 |
| E2E 测试 | 关键流程 | 登录、用药、风险 |

### 1.3 测试工具

| 类型 | 工具 | 说明 |
| --- | --- | --- |
| 单元测试 | flutter_test + mockito | 逻辑和 Provider 测试 |
| Widget 测试 | flutter_test | UI 组件测试 |
| 集成测试 | integration_test | 多模块交互 |
| E2E 测试 | patrol + flutter_test | 端到端流程 |
| Mock | mockito + build_runner | 依赖模拟 |
| 覆盖率 | coverage | 覆盖率统计 |
| 黄金测试 | golden_toolkit | UI 回归 |

## 2. 单元测试

### 2.1 Provider 测试

```dart
void main() {
  group('AuthProvider', () {
    late MockAuthRepository mockAuthRepository;
    late MockLocalStorageService mockLocalStorage;
    late AuthProvider provider;

    setUp(() {
      mockAuthRepository = MockAuthRepository();
      mockLocalStorage = MockLocalStorageService();
      provider = AuthProvider(mockAuthRepository, mockLocalStorage);
    });

    test('初始状态未登录', () {
      expect(provider.isLoggedIn, false);
      expect(provider.currentUser, isNull);
    });

    test('登录成功后状态更新', () async {
      when(mockAuthRepository.login(any, any)).thenAnswer(
        (_) async => LoginResult(
          accessToken: 'test_token',
          refreshToken: 'refresh_token',
        ),
      );
      when(mockLocalStorage.saveTokens(any, any)).thenAnswer((_) async {});
      when(mockAuthRepository.getCurrentUser()).thenAnswer(
        (_) async => User(id: '1', name: 'Test'),
      );

      await provider.login('13800138000', 'password');

      expect(provider.isLoggedIn, true);
      expect(provider.currentUser?.name, 'Test');
      verify(mockLocalStorage.saveTokens('test_token', 'refresh_token')).called(1);
    });

    test('登录失败抛出异常', () async {
      when(mockAuthRepository.login(any, any)).thenThrow(
        AuthException(code: 'INVALID_CREDENTIALS', message: '手机号或密码错误'),
      );

      expect(
        () => provider.login('13800138000', 'wrong'),
        throwsA(isA<AuthException>()),
      );
    });

    test('登出后清除状态', () async {
      when(mockAuthRepository.logout()).thenAnswer((_) async {});
      when(mockLocalStorage.clearTokens()).thenAnswer((_) async {});

      await provider.logout();

      expect(provider.isLoggedIn, false);
      expect(provider.currentUser, isNull);
    });
  });
}
```

### 2.2 工具函数测试

```dart
void main() {
  group('DateUtils', () {
    test('格式化日期', () {
      final date = DateTime(2026, 9, 4);
      expect(DateUtils.formatDate(date), '2026年09月04日');
    });

    test('计算相对时间-刚刚', () {
      final now = DateTime.now();
      expect(DateUtils.relativeTime(now), '刚刚');
    });

    test('计算相对时间-分钟前', () {
      final time = DateTime.now().subtract(const Duration(minutes: 5));
      expect(DateUtils.relativeTime(time), '5分钟前');
    });

    test('计算相对时间-小时前', () {
      final time = DateTime.now().subtract(const Duration(hours: 3));
      expect(DateUtils.relativeTime(time), '3小时前');
    });

    test('判断是否过期', () {
      final expired = DateTime.now().subtract(const Duration(days: 1));
      final notExpired = DateTime.now().add(const Duration(days: 1));
      expect(DateUtils.isExpired(expired), true);
      expect(DateUtils.isExpired(notExpired), false);
    });
  });

  group('Validator', () {
    test('手机号验证', () {
      expect(Validator.isPhone('13800138000'), true);
      expect(Validator.isPhone('12345'), false);
      expect(Validator.isPhone(''), false);
    });

    test('密码强度验证', () {
      expect(Validator.passwordStrength('123456'), PasswordStrength.weak);
      expect(Validator.passwordStrength('abc12345'), PasswordStrength.medium);
      expect(Validator.passwordStrength('Abc12345!'), PasswordStrength.strong);
    });
  });
}
```

### 2.3 模型测试

```dart
void main() {
  group('Medicine model', () {
    test('JSON 序列化', () {
      final medicine = Medicine(
        id: '1',
        name: '阿莫西林',
        dosage: '0.5g',
        frequency: '每日三次',
        updatedAt: DateTime(2026, 9, 4),
      );

      final json = medicine.toJson();
      final restored = Medicine.fromJson(json);

      expect(restored.id, medicine.id);
      expect(restored.name, medicine.name);
      expect(restored.dosage, medicine.dosage);
    });

    test('判断是否过期', () {
      final expired = Medicine(
        id: '1',
        name: 'test',
        dosage: '1g',
        frequency: 'daily',
        expiryDate: DateTime.now().subtract(const Duration(days: 1)),
        updatedAt: DateTime.now(),
      );
      expect(expired.isExpired, true);
    });
  });
}
```

## 3. Widget 测试

### 3.1 组件测试

```dart
void main() {
  group('AppButton', () {
    testWidgets('显示文本', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AppButton(text: '点击我', onPressed: () {}),
          ),
        ),
      );

      expect(find.text('点击我'), findsOneWidget);
    });

    testWidgets('点击触发回调', (tester) async {
      var pressed = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AppButton(
              text: '点击我',
              onPressed: () => pressed = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byType(AppButton));
      expect(pressed, true);
    });

    testWidgets('loading 状态显示进度条', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AppButton(text: '加载中', loading: true, onPressed: () {}),
          ),
        ),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('disabled 状态不可点击', (tester) async {
      var pressed = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AppButton(
              text: '禁用',
              disabled: true,
              onPressed: () => pressed = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byType(AppButton));
      expect(pressed, false);
    });
  });
}
```

### 3.2 页面测试

```dart
void main() {
  group('LoginPage', () {
    late MockAuthProvider mockAuthProvider;

    setUp(() {
      mockAuthProvider = MockAuthProvider();
    });

    Widget buildTestableWidget() {
      return MaterialApp(
        home: ChangeNotifierProvider<AuthProvider>.value(
          value: mockAuthProvider,
          child: const LoginPage(),
        ),
      );
    }

    testWidgets('显示登录表单', (tester) async {
      await tester.pumpWidget(buildTestableWidget());

      expect(find.text('登录'), findsWidgets);
      expect(find.byType(AppTextField), findsNWidgets(2));
      expect(find.byType(AppButton), findsOneWidget);
    });

    testWidgets('空表单显示验证错误', (tester) async {
      await tester.pumpWidget(buildTestableWidget());
      await tester.tap(find.byType(AppButton));
      await tester.pump();

      expect(find.text('请输入手机号'), findsOneWidget);
    });

    testWidgets('登录成功导航到首页', (tester) async {
      when(mockAuthProvider.login(any, any)).thenAnswer((_) async {});

      await tester.pumpWidget(buildTestableWidget());

      await tester.enterText(
        find.byKey(const Key('phone_field')),
        '13800138000',
      );
      await tester.enterText(
        find.byKey(const Key('password_field')),
        'password123',
      );
      await tester.tap(find.byType(AppButton));
      await tester.pumpAndSettle();

      verify(mockAuthProvider.login('13800138000', 'password123')).called(1);
    });
  });
}
```

## 4. 集成测试

### 4.1 用药流程测试

```dart
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  group('用药流程 E2E', () {
    testWidgets('添加药品并设置提醒', (tester) async {
      app.main();
      await tester.pumpAndSettle();

      // 登录
      await tester.enterText(find.byKey(const Key('phone')), '13800138000');
      await tester.enterText(find.byKey(const Key('password')), 'password');
      await tester.tap(find.text('登录'));
      await tester.pumpAndSettle();

      // 进入药品页
      await tester.tap(find.text('药品'));
      await tester.pumpAndSettle();

      // 添加药品
      await tester.tap(find.byKey(const Key('add_medicine')));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('name')), '阿莫西林');
      await tester.enterText(find.byKey(const Key('dosage')), '0.5g');
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();

      // 验证药品已添加
      expect(find.text('阿莫西林'), findsOneWidget);
    });
  });
}
```

## 5. Mock 配置

### 5.1 Mock 生成

```dart
// annotations
import 'package:mockito/annotations.dart';

@GenerateMocks([
  AuthRepository,
  MedicineRepository,
  ApiClient,
  LocalStorageService,
  NotificationService,
])
void main() {}
```

```bash
# 生成 Mock 代码
dart run build_runner build --delete-conflicting-outputs
```

## 6. 测试数据

### 6.1 Test Fixtures

```dart
class TestFixtures {
  static User get testUser => User(
        id: 'user_001',
        name: '测试用户',
        phone: '13800138000',
        createdAt: DateTime(2026, 1, 1),
      );

  static Household get testHousehold => Household(
        id: 'household_001',
        name: '测试家庭',
        ownerId: 'user_001',
        createdAt: DateTime(2026, 1, 1),
      );

  static Medicine get testMedicine => Medicine(
        id: 'med_001',
        name: '阿莫西林',
        dosage: '0.5g',
        frequency: '每日三次',
        updatedAt: DateTime(2026, 9, 4),
      );

  static List<Medicine> get medicineList => [
        testMedicine,
        Medicine(
          id: 'med_002',
          name: '布洛芬',
          dosage: '0.2g',
          frequency: '必要时',
          updatedAt: DateTime(2026, 9, 4),
        ),
      ];
}
```

## 7. CI 集成

### 7.1 GitHub Actions

```yaml
name: APP Test

on:
  push:
    paths:
      - 'APP/**'
  pull_request:
    paths:
      - 'APP/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.22.0'
      - run: cd APP && flutter pub get
      - run: cd APP && flutter analyze
      - run: cd APP && flutter test --coverage
      - uses: codecov/codecov-action@v3
        with:
          files: APP/coverage/lcov.info
```

## 8. 测试检查清单

- [ ] 核心业务逻辑单元测试覆盖
- [ ] Provider 状态变更测试
- [ ] 模型序列化测试
- [ ] 工具函数边界测试
- [ ] 关键 Widget 测试
- [ ] 页面交互测试
- [ ] 错误状态测试
- [ ] 加载状态测试
- [ ] 核心流程集成测试
- [ ] Mock 配置完整
- [ ] 测试数据统一管理
- [ ] CI 自动运行测试
- [ ] 覆盖率达标

---

*测试是质量的基石。全面的测试让每次变更都有信心，让每个发布都安心。*
