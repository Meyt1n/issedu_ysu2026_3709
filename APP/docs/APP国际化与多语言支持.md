# APP国际化与多语言支持

> 本文档是家健镜系统 APP 国际化与多语言支持的完整设计说明，覆盖多语言架构、文本管理、日期格式、数字格式、RTL 支持。

## 1. 概述

### 1.1 设计目标

1. 支持中文、英文双语
2. 可扩展更多语言
3. 文本与代码分离
4. 动态切换语言
5. 符合各地区习惯

### 1.2 支持语言

| 语言 | 代码 | 地区 | 状态 |
| --- | --- | --- | --- |
| 简体中文 | zh-CN | 中国大陆 | 已支持 |
| 英文 | en-US | 美国 | 已支持 |
| 繁体中文 | zh-TW | 中国台湾 | 计划中 |
| 日语 | ja-JP | 日本 | 计划中 |

## 2. 国际化架构

### 2.1 依赖配置

```yaml
dependencies:
  flutter_localizations:
    sdk: flutter
  intl: ^0.18.0
  easy_localization: ^3.0.0
```

### 2.2 初始化

```dart
import 'package:easy_localization/easy_localization.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await EasyLocalization.ensureInitialized();

  runApp(
    EasyLocalization(
      supportedLocales: [Locale('zh', 'CN'), Locale('en', 'US')],
      path: 'assets/translations',
      fallbackLocale: Locale('zh', 'CN'),
      child: MyApp(),
    ),
  );
}

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      localizationsDelegates: context.localizationDelegates,
      supportedLocales: context.supportedLocales,
      locale: context.locale,
      home: HomePage(),
    );
  }
}
```

### 2.3 翻译文件

```json
// assets/translations/zh-CN.json
{
  "app": {
    "title": "家健镜",
    "home": "首页",
    "medicine": "用药管理",
    "health": "健康数据",
    "profile": "我的"
  },
  "medicine": {
    "add": "添加药品",
    "name": "药品名称",
    "dosage": "剂量",
    "frequency": "服用频率",
    "reminder": "用药提醒",
    "taken": "已服药",
    "missed": "已漏服"
  },
  "common": {
    "confirm": "确认",
    "cancel": "取消",
    "save": "保存",
    "delete": "删除",
    "edit": "编辑",
    "loading": "加载中...",
    "error": "出错了",
    "retry": "重试",
    "no_data": "暂无数据"
  }
}
```

```json
// assets/translations/en-US.json
{
  "app": {
    "title": "HomeCare",
    "home": "Home",
    "medicine": "Medicines",
    "health": "Health",
    "profile": "Profile"
  },
  "medicine": {
    "add": "Add Medicine",
    "name": "Medicine Name",
    "dosage": "Dosage",
    "frequency": "Frequency",
    "reminder": "Reminder",
    "taken": "Taken",
    "missed": "Missed"
  },
  "common": {
    "confirm": "Confirm",
    "cancel": "Cancel",
    "save": "Save",
    "delete": "Delete",
    "edit": "Edit",
    "loading": "Loading...",
    "error": "Error",
    "retry": "Retry",
    "no_data": "No data"
  }
}
```

## 3. 文本使用

### 3.1 基本翻译

```dart
// 简单翻译
Text('app.title'.tr())  // 家健镜 / HomeCare

// 带参数
Text('medicine.reminder_time'.tr(namedArgs: {'time': '08:00'}))
// 用药提醒时间：08:00 / Reminder at: 08:00

// 复数形式
Text('medicine.count'.tr(args: ['3']))
// 3 种药品 / 3 medicines
```

### 3.2 翻译文件配置

```json
{
  "medicine": {
    "reminder_time": "用药提醒时间：{time}",
    "count": "{count} 种药品"
  }
}
```

### 3.3 性别处理

```dart
// 根据性别选择不同文本
String getGreeting(String gender) {
  return gender == 'female' ? 'welcome_ms'.tr() : 'welcome_mr'.tr();
}
```

## 4. 日期与时间

### 4.1 日期格式化

```dart
import 'package:intl/intl.dart';

class DateFormatter {
  static String formatDate(DateTime date, BuildContext context) {
    final locale = Localizations.localeOf(context).toString();
    final formatter = DateFormat.yMd(locale);
    return formatter.format(date);
  }

  static String formatDateTime(DateTime date, BuildContext context) {
    final locale = Localizations.localeOf(context).toString();
    final formatter = DateFormat.yMd(locale).add_Hm();
    return formatter.format(date);
  }

  static String formatRelative(DateTime date, BuildContext context) {
    final now = DateTime.now();
    final diff = now.difference(date);

    if (diff.inMinutes < 1) return 'just_now'.tr();
    if (diff.inMinutes < 60) return 'minutes_ago'.tr(namedArgs: {'n': diff.inMinutes.toString()});
    if (diff.inHours < 24) return 'hours_ago'.tr(namedArgs: {'n': diff.inHours.toString()});
    if (diff.inDays < 7) return 'days_ago'.tr(namedArgs: {'n': diff.inDays.toString()});
    return formatDate(date, context);
  }
}
```

### 4.2 各地区日期格式

| 地区 | 格式 | 示例 |
| --- | --- | --- |
| 中国 | yyyy-MM-dd | 2026-09-04 |
| 美国 | MM/dd/yyyy | 09/04/2026 |
| 欧洲 | dd/MM/yyyy | 04/09/2026 |
| 日本 | yyyy年MM月dd日 | 2026年09月04日 |

## 5. 数字与货币

### 5.1 数字格式化

```dart
class NumberFormatter {
  static String formatNumber(num value, BuildContext context) {
    final locale = Localizations.localeOf(context).toString();
    return NumberFormat.decimalPattern(locale).format(value);
  }

  static String formatCurrency(num value, BuildContext context) {
    final locale = Localizations.localeOf(context).toString();
    return NumberFormat.currency(locale: locale).format(value);
  }

  static String formatPercent(num value, BuildContext context) {
    final locale = Localizations.localeOf(context).toString();
    return NumberFormat.percentPattern(locale).format(value);
  }
}
```

### 5.2 各地区数字格式

| 地区 | 千位分隔 | 小数点 | 示例 |
| --- | --- | --- | --- |
| 中国 | , | . | 1,234.56 |
| 美国 | , | . | 1,234.56 |
| 欧洲 | . | , | 1.234,56 |

## 6. 语言切换

### 6.1 动态切换

```dart
class LanguageSettingsPage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('language_settings'.tr())),
      body: ListView(
        children: [
          ListTile(
            title: Text('简体中文'),
            trailing: context.locale == Locale('zh', 'CN')
                ? Icon(Icons.check)
                : null,
            onTap: () {
              context.setLocale(Locale('zh', 'CN'));
            },
          ),
          ListTile(
            title: Text('English'),
            trailing: context.locale == Locale('en', 'US')
                ? Icon(Icons.check)
                : null,
            onTap: () {
              context.setLocale(Locale('en', 'US'));
            },
          ),
        ],
      ),
    );
  }
}
```

### 6.2 持久化语言设置

```dart
class LanguageManager {
  static const _key = 'preferred_language';

  static Future<void> saveLanguage(Locale locale) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, locale.toString());
  }

  static Future<Locale?> getLanguage() async {
    final prefs = await SharedPreferences.getInstance();
    final lang = prefs.getString(_key);
    if (lang == null) return null;
    final parts = lang.split('_');
    return Locale(parts[0], parts.length > 1 ? parts[1] : null);
  }
}
```

## 7. RTL 支持

### 7.1 RTL 语言

```dart
// 阿拉伯语、希伯来语等 RTL 语言
// Flutter 自动处理方向
MaterialApp(
  builder: (context, child) {
    return Directionality(
      textDirection: context.locale.languageCode == 'ar'
          ? TextDirection.rtl
          : TextDirection.ltr,
      child: child!,
    );
  },
)
```

### 7.2 布局适配

```dart
// 使用 EdgeInsetsDirectional 代替 EdgeInsets
Container(
  padding: EdgeInsetsDirectional.only(start: 16, end: 16),
  child: Text('hello'.tr()),
)

// 使用 AlignmentDirectional
Align(
  alignment: AlignmentDirectional.centerStart,
  child: Text('hello'.tr()),
)
```

## 8. 翻译管理

### 8.1 翻译检查

```dart
// 检查缺失的翻译
class TranslationChecker {
  static Future<List<String>> checkMissingTranslations() async {
    final zh = await rootBundle.loadString('assets/translations/zh-CN.json');
    final en = await rootBundle.loadString('assets/translations/en-US.json');

    final zhKeys = _extractKeys(jsonDecode(zh));
    final enKeys = _extractKeys(jsonDecode(en));

    final missing = zhKeys.difference(enKeys);
    return missing.toList();
  }

  static Set<String> _extractKeys(Map<String, dynamic> map, [String prefix = '']) {
    final keys = <String>{};
    map.forEach((key, value) {
      final fullKey = prefix.isEmpty ? key : '$prefix.$key';
      if (value is Map) {
        keys.addAll(_extractKeys(value, fullKey));
      } else {
        keys.add(fullKey);
      }
    });
    return keys;
  }
}
```

## 9. 国际化检查清单

- [ ] 多语言架构
- [ ] 翻译文件
- [ ] 文本使用
- [ ] 日期格式化
- [ ] 数字格式化
- [ ] 货币格式化
- [ ] 语言切换
- [ ] 持久化设置
- [ ] RTL 支持
- [ ] 布局适配
- [ ] 翻译检查
- [ ] 字体适配

---

*国际化让 APP 走向世界。多语言支持、地区格式、RTL 适配，让全球用户都能流畅使用。*
