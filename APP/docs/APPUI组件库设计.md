# APP UI组件库设计

> 本文档是家健镜 APP UI 组件库的完整设计说明，覆盖设计规范、基础组件、业务组件、主题系统、响应式布局。面向移动端开发者，作为 UI 实现的权威依据。

## 1. 设计系统概述

### 1.1 设计原则

1. **一致性**：统一的视觉语言和交互模式
2. **可访问性**：支持大字体、高对比度、屏幕阅读器
3. **健康友好**：柔和配色，避免刺激，适合老年用户
4. **高效操作**：大按钮、清晰层级、减少误触
5. **可定制**：支持主题切换和字体大小调节

### 1.2 设计令牌

```dart
class AppColors {
  // 主色
  static const Color primary = Color(0xFF2E7D32);
  static const Color primaryLight = Color(0xFF60AD5E);
  static const Color primaryDark = Color(0xFF005005);

  // 辅助色
  static const Color secondary = Color(0xFFFF9800);
  static const Color accent = Color(0xFF03A9F4);

  // 功能色
  static const Color success = Color(0xFF4CAF50);
  static const Color warning = Color(0xFFFFC107);
  static const Color error = Color(0xFFF44336);
  static const Color info = Color(0xFF2196F3);

  // 风险等级
  static const Color riskSevere = Color(0xFFD32F2F);
  static const Color riskHigh = Color(0xFFFF9800);
  static const Color riskMedium = Color(0xFFFFC107);
  static const Color riskLow = Color(0xFF9E9E9E);

  // 中性色
  static const Color textPrimary = Color(0xFF212121);
  static const Color textSecondary = Color(0xFF757575);
  static const Color textDisabled = Color(0xFFBDBDBD);
  static const Color divider = Color(0xFFE0E0E0);
  static const Color background = Color(0xFFFAFAFA);
  static const Color surface = Color(0xFFFFFFFF);
}

class AppTypography {
  static const String fontFamily = 'PingFang SC';

  static const TextStyle headline1 = TextStyle(
    fontSize: 28,
    fontWeight: FontWeight.bold,
    color: AppColors.textPrimary,
  );

  static const TextStyle headline2 = TextStyle(
    fontSize: 22,
    fontWeight: FontWeight.w600,
    color: AppColors.textPrimary,
  );

  static const TextStyle bodyLarge = TextStyle(
    fontSize: 18,
    color: AppColors.textPrimary,
  );

  static const TextStyle bodyMedium = TextStyle(
    fontSize: 16,
    color: AppColors.textPrimary,
  );

  static const TextStyle bodySmall = TextStyle(
    fontSize: 14,
    color: AppColors.textSecondary,
  );

  static const TextStyle caption = TextStyle(
    fontSize: 12,
    color: AppColors.textSecondary,
  );
}

class AppSpacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 16;
  static const double lg = 24;
  static const double xl = 32;
  static const double xxl = 48;
}

class AppRadius {
  static const double sm = 4;
  static const double md = 8;
  static const double lg = 16;
  static const double xl = 24;
  static const double full = 999;
}

class AppShadows {
  static const List<BoxShadow> card = [
    BoxShadow(
      color: Color(0x14000000),
      blurRadius: 8,
      offset: Offset(0, 2),
    ),
  ];

  static const List<BoxShadow> elevated = [
    BoxShadow(
      color: Color(0x1F000000),
      blurRadius: 12,
      offset: Offset(0, 4),
    ),
  ];
}
```

## 2. 基础组件

### 2.1 按钮

```dart
class AppButton extends StatelessWidget {
  final String text;
  final VoidCallback? onPressed;
  final ButtonVariant variant;
  final ButtonSize size;
  final bool loading;
  final bool disabled;
  final IconData? icon;
  final bool fullWidth;

  const AppButton({
    super.key,
    required this.text,
    this.onPressed,
    this.variant = ButtonVariant.primary,
    this.size = ButtonSize.medium,
    this.loading = false,
    this.disabled = false,
    this.icon,
    this.fullWidth = false,
  });

  @override
  Widget build(BuildContext context) {
    final isDisabled = disabled || loading;

    return SizedBox(
      width: fullWidth ? double.infinity : null,
      height: _getHeight(),
      child: ElevatedButton(
        onPressed: isDisabled ? null : onPressed,
        style: _getButtonStyle(),
        child: loading
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (icon != null) ...[
                    Icon(icon, size: _getIconSize()),
                    const SizedBox(width: AppSpacing.sm),
                  ],
                  Text(text, style: _getTextStyle()),
                ],
              ),
      ),
    );
  }

  double _getHeight() {
    switch (size) {
      case ButtonSize.small:
        return 36;
      case ButtonSize.medium:
        return 48;
      case ButtonSize.large:
        return 56;
    }
  }

  ButtonStyle _getButtonStyle() {
    switch (variant) {
      case ButtonVariant.primary:
        return ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        );
      case ButtonVariant.secondary:
        return ElevatedButton.styleFrom(
          backgroundColor: AppColors.primaryLight.withOpacity(0.1),
          foregroundColor: AppColors.primary,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        );
      case ButtonVariant.outline:
        return OutlinedButton.styleFrom(
          foregroundColor: AppColors.primary,
          side: const BorderSide(color: AppColors.primary),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        );
      case ButtonVariant.danger:
        return ElevatedButton.styleFrom(
          backgroundColor: AppColors.error,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        );
      case ButtonVariant.text:
        return TextButton.styleFrom(
          foregroundColor: AppColors.primary,
        );
    }
  }
}

enum ButtonVariant { primary, secondary, outline, danger, text }
enum ButtonSize { small, medium, large }
```

### 2.2 卡片

```dart
class AppCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final VoidCallback? onTap;
  final Color? color;
  final List<BoxShadow>? shadow;
  final BorderRadius? borderRadius;

  const AppCard({
    super.key,
    required this.child,
    this.padding,
    this.onTap,
    this.color,
    this.shadow,
    this.borderRadius,
  });

  @override
  Widget build(BuildContext context) {
    final card = Container(
      padding: padding ?? const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: color ?? AppColors.surface,
        borderRadius: borderRadius ?? BorderRadius.circular(AppRadius.lg),
        boxShadow: shadow ?? AppShadows.card,
      ),
      child: child,
    );

    if (onTap != null) {
      return Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: borderRadius ?? BorderRadius.circular(AppRadius.lg),
          child: card,
        ),
      );
    }
    return card;
  }
}
```

### 2.3 输入框

```dart
class AppTextField extends StatefulWidget {
  final String? label;
  final String? hint;
  final TextEditingController? controller;
  final bool obscureText;
  final TextInputType? keyboardType;
  final String? Function(String?)? validator;
  final ValueChanged<String>? onChanged;
  final IconData? prefixIcon;
  final IconData? suffixIcon;
  final VoidCallback? onSuffixTap;
  final int? maxLines;
  final int? maxLength;
  final bool enabled;
  final String? errorText;

  const AppTextField({
    super.key,
    this.label,
    this.hint,
    this.controller,
    this.obscureText = false,
    this.keyboardType,
    this.validator,
    this.onChanged,
    this.prefixIcon,
    this.suffixIcon,
    this.onSuffixTap,
    this.maxLines = 1,
    this.maxLength,
    this.enabled = true,
    this.errorText,
  });

  @override
  State<AppTextField> createState() => _AppTextFieldState();
}

class _AppTextFieldState extends State<AppTextField> {
  late bool _obscureText;

  @override
  void initState() {
    super.initState();
    _obscureText = widget.obscureText;
  }

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: widget.controller,
      obscureText: _obscureText,
      keyboardType: widget.keyboardType,
      validator: widget.validator,
      onChanged: widget.onChanged,
      maxLines: widget.obscureText ? 1 : widget.maxLines,
      maxLength: widget.maxLength,
      enabled: widget.enabled,
      style: AppTypography.bodyMedium,
      decoration: InputDecoration(
        labelText: widget.label,
        hintText: widget.hint,
        errorText: widget.errorText,
        prefixIcon: widget.prefixIcon != null
            ? Icon(widget.prefixIcon, color: AppColors.textSecondary)
            : null,
        suffixIcon: widget.suffixIcon != null
            ? IconButton(
                icon: Icon(
                  _obscureText && widget.obscureText
                      ? Icons.visibility_off
                      : widget.suffixIcon,
                ),
                onPressed: widget.obscureText
                    ? () => setState(() => _obscureText = !_obscureText)
                    : widget.onSuffixTap,
              )
            : null,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.divider),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.divider),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.primary, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: const BorderSide(color: AppColors.error),
        ),
        filled: true,
        fillColor: widget.enabled ? AppColors.surface : AppColors.background,
      ),
    );
  }
}
```

### 2.4 标签

```dart
class AppBadge extends StatelessWidget {
  final String text;
  final Color? color;
  final Color? textColor;
  final BadgeSize size;

  const AppBadge({
    super.key,
    required this.text,
    this.color,
    this.textColor,
    this.size = BadgeSize.medium,
  });

  factory AppBadge.risk(String level) {
    switch (level) {
      case 'severe':
        return AppBadge(text: '严重', color: AppColors.riskSevere);
      case 'high':
        return AppBadge(text: '高', color: AppColors.riskHigh);
      case 'medium':
        return AppBadge(text: '中', color: AppColors.riskMedium);
      default:
        return AppBadge(text: '低', color: AppColors.riskLow);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: size == BadgeSize.small ? 6 : 10,
        vertical: size == BadgeSize.small ? 2 : 4,
      ),
      decoration: BoxDecoration(
        color: (color ?? AppColors.primary).withOpacity(0.15),
        borderRadius: BorderRadius.circular(AppRadius.full),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: size == BadgeSize.small ? 10 : 12,
          fontWeight: FontWeight.w500,
          color: textColor ?? color ?? AppColors.primary,
        ),
      ),
    );
  }
}
```

## 3. 业务组件

### 3.1 药品卡片

```dart
class MedicineCard extends StatelessWidget {
  final Medicine medicine;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  const MedicineCard({
    super.key,
    required this.medicine,
    this.onTap,
    this.onLongPress,
  });

  @override
  Widget build(BuildContext context) {
    return AppCard(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: AppColors.primary.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: const Icon(Icons.medication, color: AppColors.primary),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(medicine.name, style: AppTypography.bodyLarge),
                    const SizedBox(height: 4),
                    Text(
                      '${medicine.dosage} · ${medicine.frequency}',
                      style: AppTypography.bodySmall,
                    ),
                  ],
                ),
              ),
              if (medicine.isExpired)
                const AppBadge(text: '已过期', color: AppColors.error),
            ],
          ),
          if (medicine.expiryDate != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                Icon(Icons.event, size: 14, color: AppColors.textSecondary),
                const SizedBox(width: 4),
                Text(
                  '有效期至 ${medicine.expiryDate!.toString().substring(0, 10)}',
                  style: AppTypography.caption,
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
```

### 3.2 风险卡片

```dart
class RiskCard extends StatelessWidget {
  final RiskEvent risk;
  final VoidCallback? onAcknowledge;
  final VoidCallback? onTap;

  const RiskCard({
    super.key,
    required this.risk,
    this.onAcknowledge,
    this.onTap,
  });

  Color get _riskColor {
    switch (risk.riskLevel) {
      case 'severe':
        return AppColors.riskSevere;
      case 'high':
        return AppColors.riskHigh;
      case 'medium':
        return AppColors.riskMedium;
      default:
        return AppColors.riskLow;
    }
  }

  @override
  Widget build(BuildContext context) {
    return AppCard(
      color: _riskColor.withOpacity(0.05),
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 8,
                height: 40,
                decoration: BoxDecoration(
                  color: _riskColor,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(risk.title, style: AppTypography.bodyLarge),
                    const SizedBox(height: 4),
                    Text(risk.description, style: AppTypography.bodySmall),
                  ],
                ),
              ),
              AppBadge.risk(risk.riskLevel),
            ],
          ),
          if (risk.suggestion != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Container(
              padding: const EdgeInsets.all(AppSpacing.sm),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(AppRadius.sm),
              ),
              child: Row(
                children: [
                  const Icon(Icons.lightbulb_outline,
                      size: 16, color: AppColors.secondary),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(risk.suggestion!,
                        style: AppTypography.caption),
                  ),
                ],
              ),
            ),
          ],
          if (onAcknowledge != null && !risk.acknowledged) ...[
            const SizedBox(height: AppSpacing.sm),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: onAcknowledge,
                child: const Text('已知晓'),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
```

### 3.3 成员头像

```dart
class MemberAvatar extends StatelessWidget {
  final String name;
  final String? avatarUrl;
  final double size;
  final Color? backgroundColor;

  const MemberAvatar({
    super.key,
    required this.name,
    this.avatarUrl,
    this.size = 48,
    this.backgroundColor,
  });

  String get _initial => name.isNotEmpty ? name[0] : '?';

  Color get _defaultColor {
    final hash = name.hashCode;
    final colors = [
      const Color(0xFFE3F2FD),
      const Color(0xFFE8F5E9),
      const Color(0xFFFFF3E0),
      const Color(0xFFFCE4EC),
      const Color(0xFFF3E5F5),
    ];
    return colors[hash % colors.length];
  }

  @override
  Widget build(BuildContext context) {
    if (avatarUrl != null) {
      return ClipOval(
        child: CachedNetworkImage(
          imageUrl: avatarUrl!,
          width: size,
          height: size,
          fit: BoxFit.cover,
          placeholder: (context, url) => _buildInitial(),
          errorWidget: (context, url, error) => _buildInitial(),
        ),
      );
    }
    return _buildInitial();
  }

  Widget _buildInitial() {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: backgroundColor ?? _defaultColor,
        shape: BoxShape.circle,
      ),
      child: Center(
        child: Text(
          _initial,
          style: TextStyle(
            fontSize: size * 0.4,
            fontWeight: FontWeight.w600,
            color: AppColors.textPrimary,
          ),
        ),
      ),
    );
  }
}
```

## 4. 主题系统

### 4.1 主题配置

```dart
class AppTheme {
  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        brightness: Brightness.light,
      ),
      scaffoldBackgroundColor: AppColors.background,
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.surface,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
        centerTitle: true,
      ),
      cardTheme: CardThemeData(
        color: AppColors.surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          minimumSize: const Size(0, 48),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
      ),
    );
  }

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        brightness: Brightness.dark,
      ),
    );
  }
}
```

### 4.2 字体大小调节

```dart
class TextScaleProvider extends ChangeNotifier {
  double _scale = 1.0;
  static const double minScale = 0.8;
  static const double maxScale = 1.5;

  double get scale => _scale;

  void setScale(double value) {
    _scale = value.clamp(minScale, maxScale);
    notifyListeners();
  }

  void increase() => setScale(_scale + 0.1);
  void decrease() => setScale(_scale - 0.1);
  void reset() => setScale(1.0);
}
```

## 5. 响应式布局

### 5.1 断点

```dart
class Breakpoints {
  static const double mobile = 600;
  static const double tablet = 1024;
  static const double desktop = 1440;
}

class ResponsiveBuilder extends StatelessWidget {
  final WidgetBuilder mobile;
  final WidgetBuilder? tablet;
  final WidgetBuilder? desktop;

  const ResponsiveBuilder({
    super.key,
    required this.mobile,
    this.tablet,
    this.desktop,
  });

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.of(context).size.width;

    if (width >= Breakpoints.desktop && desktop != null) {
      return desktop!(context);
    } else if (width >= Breakpoints.tablet && tablet != null) {
      return tablet!(context);
    }
    return mobile(context);
  }
}
```

## 6. UI组件检查清单

- [ ] 设计令牌统一管理
- [ ] 按钮支持多种变体和尺寸
- [ ] 卡片支持点击和阴影
- [ ] 输入框支持验证和错误提示
- [ ] 标签支持风险等级
- [ ] 业务组件复用性高
- [ ] 主题支持亮/暗模式
- [ ] 字体大小可调节
- [ ] 响应式布局适配
- [ ] 可访问性支持
- [ ] 组件有示例代码
- [ ] 组件有单元测试

---

*统一的组件库是 APP 质量的保证。一致、友好、可访问的 UI，让每个家庭成员都能轻松使用。*
