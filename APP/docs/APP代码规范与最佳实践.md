# APP代码规范与最佳实践

> 本文档是家健镜系统 APP 代码规范与最佳实践的完整指南，覆盖命名规范、代码风格、架构规范、测试规范、Git 规范。

## 1. 概述

### 1.1 规范目标

1. 代码风格统一
2. 提高可读性
3. 减少 Bug
4. 便于维护
5. 提升协作效率

### 1.2 规范层级

| 层级 | 说明 | 强制执行 |
| --- | --- | --- |
| 必须 | 不遵守会导致问题 | 是 |
| 推荐 | 最佳实践 | 建议遵守 |
| 可选 | 个人偏好 | 自由选择 |

## 2. 命名规范

### 2.1 文件命名

```dart
// 好：小写+下划线
medicine_list_page.dart
user_profile_model.dart
api_service.dart

// 不好
MedicineListPage.dart
userProfile.dart
API-service.dart
```

### 2.2 类命名

```dart
// 类名：PascalCase
class MedicineListPage {}
class UserProfileModel {}
class ApiService {}

// 枚举：PascalCase
enum MedicineType { tablet, capsule, injection }

// 抽象类：PascalCase，可加 I 前缀（可选）
abstract class IMedicineRepository {}
abstract class MedicineRepository {}
```

### 2.3 变量命名

```dart
// 变量：camelCase
String medicineName = '';
int dosageCount = 0;
bool isLoading = false;

// 常量：lowerCamelCase（Dart 推荐）
const int maxRetries = 3;
const String apiBaseUrl = 'https://api.homecare.com';

// 布尔值：is/has/can 前缀
bool isEnabled = true;
bool hasData = false;
bool canSubmit = true;

// 集合：复数形式
List<Medicine> medicines = [];
Map<String, User> users = {};
Set<String> selectedIds = {};
```

### 2.4 函数命名

```dart
// 函数：camelCase，动词开头
Future<void> loadMedicines() async {}
Future<Medicine> getMedicine(String id) async {}
bool validateInput(String value) {}
void updateState() {}

// 回调函数：动词过去式或 on 前缀
void onMedicineTap(Medicine medicine) {}
void onDataLoaded(List<Medicine> data) {}
```

## 3. 代码风格

### 3.1 格式化

```dart
// 行宽：80 字符
// 缩进：2 空格

// 好
class Medicine {
  final String id;
  final String name;
  final String dosage;

  const Medicine({
    required this.id,
    required this.name,
    required this.dosage,
  });
}

// 不好（缩进4空格）
class Medicine {
    final String id;
    final String name;
}
```

### 3.2 导入顺序

```dart
// 1. Dart SDK 导入
import 'dart:async';
import 'dart:convert';

// 2. 第三方包导入
import 'package:flutter/material.dart';
import 'package:http/http.dart';
import 'package:provider/provider.dart';

// 3. 相对路径导入
import '../models/medicine.dart';
import '../services/api_service.dart';
import 'medicine_card.dart';

// 每组之间空一行
```

### 3.3 注释规范

```dart
// 文档注释：///，用于公共 API
/// 获取药品列表
///
/// 根据 [memberId] 获取该成员的所有药品
/// 返回 [List<Medicine>]，失败时抛出 [ApiException]
Future<List<Medicine>> getMedicines(String memberId) async {}

// 单行注释：//，解释为什么
// 这里需要延迟一帧，等待布局完成
WidgetsBinding.instance.addPostFrameCallback((_) {});

// TODO 注释
// TODO: 实现分页加载
// FIXME: 这里有内存泄漏
// HACK: 临时解决方案，后续优化
```

### 3.4 函数长度

```dart
// 好：函数短小，职责单一
Future<void> submitForm() async {
  if (!_validate()) return;
  await _saveData();
  _navigateToNext();
}

bool _validate() {
  return _formKey.currentState!.validate();
}

Future<void> _saveData() async {
  await _repository.save(_formData);
}

void _navigateToNext() {
  Navigator.pushNamed(context, '/success');
}

// 不好：函数过长
Future<void> submitForm() async {
  // 50行验证逻辑...
  // 30行保存逻辑...
  // 20行导航逻辑...
}
```

## 4. 架构规范

### 4.1 分层依赖

```dart
// presentation -> domain -> data
// 依赖方向：外层依赖内层

// 好：domain 不依赖 data
class GetMedicinesUseCase {
  final MedicineRepository repository;  // 依赖抽象
  GetMedicinesUseCase(this.repository);
}

// 不好：domain 依赖 data
class GetMedicinesUseCase {
  final MedicineApi api;  // 依赖具体实现
  GetMedicinesUseCase(this.api);
}
```

### 4.2 状态管理

```dart
// 使用 Provider/ChangeNotifier
class MedicineViewModel extends ChangeNotifier {
  final GetMedicinesUseCase _useCase;

  List<Medicine> _medicines = [];
  List<Medicine> get medicines => _medicines;

  bool _isLoading = false;
  bool get isLoading => _isLoading;

  Future<void> load(String memberId) async {
    _isLoading = true;
    notifyListeners();

    final result = await _useCase(memberId);
    result.fold(
      (error) => _error = error,
      (data) => _medicines = data,
    );

    _isLoading = false;
    notifyListeners();
  }
}
```

### 4.3 Widget 规范

```dart
// 好：拆分小部件
class MedicineList extends StatelessWidget {
  final List<Medicine> medicines;

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      itemCount: medicines.length,
      itemBuilder: (context, index) => MedicineCard(medicine: medicines[index]),
    );
  }
}

class MedicineCard extends StatelessWidget {
  final Medicine medicine;

  @override
  Widget build(BuildContext context) {
    return Card(child: ListTile(title: Text(medicine.name)));
  }
}

// 不好：一个大 build 方法
class MedicineList extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    // 100行嵌套布局...
  }
}
```

## 5. 错误处理

### 5.1 异常处理

```dart
// 好：捕获具体异常
try {
  await _api.getMedicines();
} on SocketException {
  throw NetworkFailure();
} on TimeoutException {
  throw TimeoutFailure();
} catch (e) {
  throw UnknownFailure(e.toString());
}

// 不好：吞掉异常
try {
  await _api.getMedicines();
} catch (e) {
  print(e);  // 只打印不处理
}
```

### 5.2 空安全

```dart
// 好：明确处理空值
String? name = medicine.name;
if (name != null) {
  print(name.length);  // 自动类型提升
}

// 使用默认值
String displayName = medicine.name ?? '未知药品';

// 不好：强制非空
String name = medicine.name!;  // 可能崩溃
```

## 6. 测试规范

### 6.1 测试命名

```dart
// 好：描述测试场景
void main() {
  group('MedicineViewModel', () {
    test('loadMedicines_成功时更新列表', () {});
    test('loadMedicines_网络错误时设置错误状态', () {});
    test('loadMedicines_加载中时isLoading为true', () {});
  });
}

// 不好：模糊命名
test('test1', () {});
test('load', () {});
```

### 6.2 测试结构

```dart
test('描述', () {
  // Arrange：准备
  final repository = MockMedicineRepository();
  final viewModel = MedicineViewModel(repository);

  // Act：执行
  viewModel.load('memberId');

  // Assert：断言
  expect(viewModel.isLoading, true);
});
```

## 7. Git 规范

### 7.1 提交信息

```
# 格式：<type>(<scope>): <subject>

# type:
# feat: 新功能
# fix: 修复bug
# docs: 文档
# style: 格式
# refactor: 重构
# test: 测试
# chore: 构建/工具

# 好
feat(medicine): 添加药品搜索功能
fix(api): 修复登录接口超时问题
docs(readme): 更新部署说明

# 不好
更新代码
修复bug
test
```

### 7.2 分支命名

```
# 格式：<type>/<description>

# 好
feat/medicine-search
fix/login-timeout
docs/api-specification

# 不好
new-feature
fix-bug
branch1
```

## 8. 性能规范

### 8.1 避免不必要的重建

```dart
// 好：使用 const 构造函数
const Text('药品名称');
const EdgeInsets.all(16);

// 好：拆分 Widget，避免整体重建
class MedicineCard extends StatelessWidget {
  final Medicine medicine;
  const MedicineCard({required this.medicine});
}

// 不好：每次都创建新对象
Text('药品名称', style: TextStyle(fontSize: 16));  // TextStyle 每次创建
```

### 8.2 列表优化

```dart
// 好：使用 ListView.builder
ListView.builder(
  itemCount: medicines.length,
  itemBuilder: (context, index) => MedicineCard(medicine: medicines[index]),
)

// 不好：使用 Column 渲染大量数据
Column(
  children: medicines.map((m) => MedicineCard(medicine: m)).toList(),
)
```

## 9. 代码规范检查清单

- [ ] 文件命名
- [ ] 类命名
- [ ] 变量命名
- [ ] 函数命名
- [ ] 代码格式化
- [ ] 导入顺序
- [ ] 注释规范
- [ ] 函数长度
- [ ] 分层依赖
- [ ] 状态管理
- [ ] 错误处理
- [ ] 空安全

---

*统一的规范是团队协作的基础。清晰的命名、一致的风格，让代码易读易维护。*
