# APP表单处理与验证设计

> 本文档是家健镜系统APP表单处理与验证设计的完整设计说明。

## 1. 概述

### 1.1 设计目标

1. 数据校验准确
2. 用户体验流畅
3. 错误提示清晰
4. 支持复杂表单
5. 性能高效

### 1.2 核心概念

| 概念 | 说明 |
| --- | --- |
| 同步验证 | 输入时实时验证 |
| 异步验证 | 提交时验证 |
| 表单状态 | 管理表单数据和验证状态 |

## 2. 表单状态管理

```dart
class FormController {
  final Map<String, dynamic> _values = {};
  final Map<String, String?> _errors = {};
  final Map<String, bool> _touched = {};

  void setValue(String field, dynamic value) {
    _values[field] = value;
    _validateField(field);
  }

  void _validateField(String field) {
    final validators = _validators[field];
    if (validators != null) {
      for (final validator in validators) {
        final error = validator(_values[field]);
        if (error != null) {
          _errors[field] = error;
          return;
        }
      }
    }
    _errors[field] = null;
  }

  bool get isValid => _errors.values.every((e) => e == null);
}
```

## 3. 验证规则

```dart
class Validators {
  static String? required(String? value) {
    if (value == null || value.isEmpty) return '此项为必填';
    return null;
  }

  static String? email(String? value) {
    if (value == null || value.isEmpty) return null;
    final regex = RegExp(r'^[\w-\.]+@([\w-]+\.)+[\w-]{2,4}$');
    if (!regex.hasMatch(value)) return '邮箱格式不正确';
    return null;
  }

  static String? phone(String? value) {
    if (value == null || value.isEmpty) return null;
    final regex = RegExp(r'^1[3-9]\d{9}$');
    if (!regex.hasMatch(value)) return '手机号格式不正确';
    return null;
  }
}
```

## 4. 异步验证

```dart
class AsyncValidators {
  static Future<String?> usernameExists(String username) async {
    final exists = await api.checkUsername(username);
    if (exists) return '用户名已存在';
    return null;
  }
}
```

## 检查清单

- [ ] 表单状态管理
- [ ] 同步验证
- [ ] 异步验证
- [ ] 错误提示
- [ ] 提交验证
- [ ] 表单重置

---

*APP表单处理与验证设计是系统的重要组成部分。*