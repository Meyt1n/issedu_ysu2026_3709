# APP深色模式与主题设计

> 本文档是家健镜系统 APP 深色模式与主题的完整设计说明，覆盖主题系统、颜色规范、组件适配、用户偏好。

## 1. 概述

### 1.1 设计目标

1. 支持深色/浅色模式
2. 跟随系统设置
3. 可手动切换
4. 自定义主题色
5. 护眼舒适

### 1.2 主题模式

| 模式 | 说明 | 适用场景 |
| --- | --- | --- |
| 浅色模式 | 白色背景，深色文字 | 白天、明亮环境 |
| 深色模式 | 深色背景，浅色文字 | 夜间、暗光环境 |
| 跟随系统 | 自动切换 | 默认 |

## 2. 主题系统

### 2.1 ThemeData

```dart
class AppTheme {
  static ThemeData lightTheme = ThemeData(
    brightness: Brightness.light,
    primaryColor: Color(0xFF2196F3),
    scaffoldBackgroundColor: Color(0xFFF5F5F5),
    cardColor: Colors.white,
    textTheme: TextTheme(
      headlineLarge: TextStyle(color: Color(0xFF212121)),
      bodyLarge: TextStyle(color: Color(0xFF424242)),
    ),
    colorScheme: ColorScheme.light(
      primary: Color(0xFF2196F3),
      secondary: Color(0xFF4CAF50),
      error: Color(0xFFF44336),
    ),
  );

  static ThemeData darkTheme = ThemeData(
    brightness: Brightness.dark,
    primaryColor: Color(0xFF64B5F6),
    scaffoldBackgroundColor: Color(0xFF121212),
    cardColor: Color(0xFF1E1E1E),
    textTheme: TextTheme(
      headlineLarge: TextStyle(color: Color(0xFFFFFFFF)),
      bodyLarge: TextStyle(color: Color(0xFFE0E0E0)),
    ),
    colorScheme: ColorScheme.dark(
      primary: Color(0xFF64B5F6),
      secondary: Color(0xFF81C784),
      error: Color(0xFFEF5350),
    ),
  );
}
```

### 2.2 主题管理

```dart
class ThemeProvider extends ChangeNotifier {
  ThemeMode _themeMode = ThemeMode.system;
  ThemeMode get themeMode => _themeMode;

  Future<void> setThemeMode(ThemeMode mode) async {
    _themeMode = mode;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('theme_mode', mode.name);
    notifyListeners();
  }

  Future<void> loadThemeMode() async {
    final prefs = await SharedPreferences.getInstance();
    final mode = prefs.getString('theme_mode');
    if (mode != null) {
      _themeMode = ThemeMode.values.firstWhere((m) => m.name == mode);
    }
  }
}
```

### 2.3 自定义主题色

```dart
class CustomTheme {
  final Color primary;
  final Color secondary;
  final Color accent;

  CustomTheme({
    required this.primary,
    required this.secondary,
    required this.accent,
  });

  static final List<CustomTheme> presets = [
    CustomTheme(
      primary: Color(0xFF2196F3),
      secondary: Color(0xFF4CAF50),
      accent: Color(0xFFFF9800),
    ),
    CustomTheme(
      primary: Color(0xFF9C27B0),
      secondary: Color(0xFF00BCD4),
      accent: Color(0xFFFF5722),
    ),
  ];
}
```

## 3. 颜色规范

### 3.1 浅色模式

| 用途 | 颜色 | 色值 |
| --- | --- | --- |
| 主背景 | 浅灰 | #F5F5F5 |
| 卡片背景 | 白色 | #FFFFFF |
| 主文字 | 深灰 | #212121 |
| 次文字 | 中灰 | #757575 |
| 分割线 | 浅灰 | #E0E0E0 |
| 主色 | 蓝色 | #2196F3 |
| 成功 | 绿色 | #4CAF50 |
| 警告 | 橙色 | #FF9800 |
| 错误 | 红色 | #F44336 |

### 3.2 深色模式

| 用途 | 颜色 | 色值 |
| --- | --- | --- |
| 主背景 | 深黑 | #121212 |
| 卡片背景 | 深灰 | #1E1E1E |
| 主文字 | 白色 | #FFFFFF |
| 次文字 | 浅灰 | #B0B0B0 |
| 分割线 | 中灰 | #333333 |
| 主色 | 浅蓝 | #64B5F6 |
| 成功 | 浅绿 | #81C784 |
| 警告 | 浅橙 | #FFB74D |
| 错误 | 浅红 | #EF5350 |

### 3.3 颜色扩展

```dart
extension AppColors on ColorScheme {
  Color get success => brightness == Brightness.dark
      ? Color(0xFF81C784)
      : Color(0xFF4CAF50);

  Color get warning => brightness == Brightness.dark
      ? Color(0xFFFFB74D)
      : Color(0xFFFF9800);

  Color get danger => brightness == Brightness.dark
      ? Color(0xFFEF5350)
      : Color(0xFFF44336);
}
```

## 4. 组件适配

### 4.1 自适应组件

```dart
class AdaptiveCard extends StatelessWidget {
  final Widget child;
  AdaptiveCard({required this.child});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Card(
      color: isDark ? Color(0xFF1E1E1E) : Colors.white,
      elevation: isDark ? 0 : 2,
      child: child,
    );
  }
}
```

### 4.2 图片适配

```dart
class AdaptiveImage extends StatelessWidget {
  final String lightImage;
  final String darkImage;

  AdaptiveImage({required this.lightImage, required this.darkImage});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Image.asset(isDark ? darkImage : lightImage);
  }
}
```

### 4.3 状态颜色

```dart
class StatusBadge extends StatelessWidget {
  final String status;
  StatusBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    Color bgColor;
    Color textColor;

    switch (status) {
      case 'success':
        bgColor = colors.success.withOpacity(0.2);
        textColor = colors.success;
        break;
      case 'warning':
        bgColor = colors.warning.withOpacity(0.2);
        textColor = colors.warning;
        break;
      case 'error':
        bgColor = colors.error.withOpacity(0.2);
        textColor = colors.error;
        break;
      default:
        bgColor = colors.primary.withOpacity(0.2);
        textColor = colors.primary;
    }

    return Container(
      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(status, style: TextStyle(color: textColor, fontSize: 12)),
    );
  }
}
```

## 5. 用户偏好

### 5.1 设置页面

```dart
class ThemeSettingsPage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('主题设置')),
      body: ListView(
        children: [
          ListTile(
            title: Text('外观模式'),
            subtitle: Text('选择浅色、深色或跟随系统'),
            trailing: DropdownButton<ThemeMode>(
              value: context.watch<ThemeProvider>().themeMode,
              items: [
                DropdownMenuItem(value: ThemeMode.system, child: Text('跟随系统')),
                DropdownMenuItem(value: ThemeMode.light, child: Text('浅色模式')),
                DropdownMenuItem(value: ThemeMode.dark, child: Text('深色模式')),
              ],
              onChanged: (mode) {
                context.read<ThemeProvider>().setThemeMode(mode!);
              },
            ),
          ),
        ],
      ),
    );
  }
}
```

## 6. 深色模式检查清单

- [ ] ThemeData 配置
- [ ] 主题管理
- [ ] 自定义主题色
- [ ] 颜色规范
- [ ] 组件适配
- [ ] 图片适配
- [ ] 状态颜色
- [ ] 用户偏好设置
- [ ] 跟随系统
- [ ] 手动切换
- [ ] 对比度检查
- [ ] 护眼模式

---

*深色模式是视觉体验的细节。舒适、统一的主题设计，让用户在任何环境下都能舒适使用。*
