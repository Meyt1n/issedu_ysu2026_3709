# APP国际化与本地化设计

> 本文档是家健镜系统 APP 国际化与本地化的完整设计说明，覆盖多语言、时区、格式、文化适配。

## 1. 国际化概述

### 1.1 设计目标

1. 多语言支持：支持中文、英文等
2. 时区适配：正确处理不同时区
3. 格式本地化：日期、数字、货币
4. 文化适配：尊重不同文化习惯
5. 易于扩展：新增语言无需改代码

### 1.2 支持语言

| 语言 | 代码 | 状态 |
| --- | --- | --- |
| 简体中文 | zh_CN | 已支持 |
| 繁体中文 | zh_TW | 计划中 |
| 英语 | en_US | 计划中 |
| 日语 | ja_JP | 计划中 |

## 2. 多语言实现

### 2.1 Flutter 国际化配置

```yaml
# pubspec.yaml
dependencies:
  flutter_localizations:
    sdk: flutter
  intl: ^0.18.0

flutter:
  generate: true
```

```yaml
# l10n.yaml
arb-dir: lib/l10n
template-arb-file: app_zh.arb
output-localization-file: app_localizations.dart
```

### 2.2 ARB 文件

```json
{
  "@@locale": "zh",
  "appTitle": "家健镜",
  "@appTitle": {
    "description": "应用标题"
  },
  "medicineTitle": "药品管理",
  "addMedicine": "添加药品",
  "deleteConfirm": "确定要删除 {name} 吗？",
  "@deleteConfirm": {
    "placeholders": {
      "name": {
        "type": "String",
        "example": "阿莫西林"
      }
    }
  },
  "medicineCount": "{count, plural, =0{没有药品} =1{1 种药品} other{{count} 种药品}}",
  "save": "保存",
  "cancel": "取消",
  "confirm": "确认"
}
```

### 2.3 使用翻译

```dart
class MedicinePage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.medicineTitle),
      ),
      body: Center(
        child: Text(l10n.medicineCount(5)),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () {},
        child: Icon(Icons.add),
        tooltip: l10n.addMedicine,
      ),
    );
  }
}
```

### 2.4 语言切换

```dart
class LanguageProvider extends ChangeNotifier {
  Locale? _locale;

  Locale? get locale => _locale;

  Future<void> setLocale(Locale locale) async {
    _locale = locale;
    await SharedPreferences.getInstance().then((prefs) {
      prefs.setString('language', locale.languageCode);
    });
    notifyListeners();
  }

  Future<void> loadLocale() async {
    final prefs = await SharedPreferences.getInstance();
    final lang = prefs.getString('language');
    if (lang != null) {
      _locale = Locale(lang);
    }
  }
}
```

## 3. 时区处理

### 3.1 时区显示

```dart
class TimeZoneHelper {
  static String formatDateTime(DateTime dt, BuildContext context) {
    final localDt = dt.toLocal();
    final format = DateFormat.yMMMMd(Localizations.localeOf(context).toString());
    return format.format(localDt);
  }

  static String formatTime(DateTime dt, BuildContext context) {
    final localDt = dt.toLocal();
    final format = DateFormat.Hm(Localizations.localeOf(context).toString());
    return format.format(localDt);
  }
}
```

### 3.2 用药提醒时区

```dart
class ReminderScheduler {
  static Future<void> scheduleReminder(
    Medicine medicine,
    TimeOfDay time,
  ) async {
    final now = DateTime.now();
    final scheduled = DateTime(
      now.year, now.month, now.day, time.hour, time.minute,
    );

    // 转换为本地时区
    final localTime = scheduled.toLocal();

    await flutterLocalNotificationsPlugin.show(
      medicine.id.hashCode,
      '用药提醒',
      '该服用 ${medicine.name} 了',
      NotificationDetails(
        android: AndroidNotificationDetails(
          'medication', '用药提醒',
        ),
      ),
    );
  }
}
```

## 4. 格式本地化

### 4.1 数字格式

```dart
class NumberFormatter {
  static String format(double value, BuildContext context) {
    final locale = Localizations.localeOf(context).toString();
    final format = NumberFormat.decimalPattern(locale);
    return format.format(value);
  }

  static String formatPercent(double value, BuildContext context) {
    final locale = Localizations.localeOf(context).toString();
    final format = NumberFormat.percentPattern(locale);
    return format.format(value);
  }
}
```

### 4.2 日期格式

```dart
class DateFormatter {
  static String formatDate(DateTime date, BuildContext context) {
    final locale = Localizations.localeOf(context).toString();
    return DateFormat.yMd(locale).format(date);
  }

  static String formatRelative(DateTime date, BuildContext context) {
    final now = DateTime.now();
    final diff = now.difference(date);

    final l10n = AppLocalizations.of(context)!;

    if (diff.inDays == 0) {
      return l10n.today;
    } else if (diff.inDays == 1) {
      return l10n.yesterday;
    } else if (diff.inDays < 7) {
      return l10n.daysAgo(diff.inDays);
    } else {
      return formatDate(date, context);
    }
  }
}
```

## 5. 文化适配

### 5.1 文本方向

```dart
class DirectionalLayout extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final isRTL = Directionality.of(context) == TextDirection.rtl;

    return Row(
      children: [
        if (!isRTL) Icon(Icons.arrow_back),
        Text('内容'),
        if (isRTL) Icon(Icons.arrow_forward),
      ],
    );
  }
}
```

### 5.2 颜色和图标

- 不同文化对颜色的理解不同
- 避免使用文化敏感的图标
- 提供可配置的主题

## 6. 国际化检查清单

- [ ] ARB 翻译文件
- [ ] 语言切换
- [ ] 时区处理
- [ ] 日期格式本地化
- [ ] 数字格式本地化
- [ ] 复数形式
- [ ] 性别处理
- [ ] 文本方向（RTL）
- [ ] 文化适配
- [ ] 字体支持
- [ ] 布局适配
- [ ] 翻译质量检查

---

*国际化让产品走向世界。尊重语言、时区和文化差异，让每个用户都有亲切的体验。*
