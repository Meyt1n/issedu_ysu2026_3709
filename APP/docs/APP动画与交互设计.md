# APP动画与交互设计

> 本文档是家健镜 APP 动画与交互的完整设计说明，覆盖动画规范、页面转场、组件动画、手势交互、性能优化。面向移动端开发者，作为动画实现的权威依据。

## 1. 动画设计原则

### 1.1 设计目标

1. **自然流畅**：动画符合物理规律，不生硬
2. **有意义**：每个动画都有目的，不为了动画而动画
3. **性能优先**：60fps 流畅运行，不丢帧
4. **可访问**：支持减少动态效果偏好
5. **一致**：相同交互有相同的动画反馈

### 1.2 动画时长规范

| 动画类型 | 时长 | 曲线 |
| --- | --- | --- |
| 按钮按压 | 100ms | easeOut |
| 页面进入 | 300ms | easeInOut |
| 页面退出 | 250ms | easeIn |
| 底部弹出 | 300ms | easeOutCubic |
| 列表项出现 | 200ms | easeOut |
| 展开/收起 | 250ms | easeInOut |
| 加载旋转 | 循环 | linear |
| 成功反馈 | 500ms | easeOutBack |

### 1.3 动画曲线

```dart
class AppAnimations {
  static const Curve easeOut = Curves.easeOut;
  static const Curve easeIn = Curves.easeIn;
  static const Curve easeInOut = Curves.easeInOut;
  static const Curve easeOutCubic = Curves.easeOutCubic;
  static const Curve easeOutBack = Curves.easeOutBack;
  static const Curve bounce = Curves.bounceOut;
  static const Curve elastic = Curves.elasticOut;

  // 自定义弹簧动画
  static const SpringDescription spring = SpringDescription(
    mass: 1,
    stiffness: 100,
    damping: 15,
  );
}
```

## 2. 页面转场动画

### 2.1 自定义页面路由

```dart
class SlideRightRoute extends PageRouteBuilder {
  final Widget page;

  SlideRightRoute({required this.page})
      : super(
          pageBuilder: (context, animation, secondaryAnimation) => page,
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            const begin = Offset(1.0, 0.0);
            const end = Offset.zero;
            const curve = Curves.easeInOut;
            var tween = Tween(begin: begin, end: end)
                .chain(CurveTween(curve: curve));
            return SlideTransition(
              position: animation.drive(tween),
              child: child,
            );
          },
          transitionDuration: const Duration(milliseconds: 300),
        );
}

class FadeRoute extends PageRouteBuilder {
  final Widget page;

  FadeRoute({required this.page})
      : super(
          pageBuilder: (context, animation, secondaryAnimation) => page,
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            return FadeTransition(opacity: animation, child: child);
          },
          transitionDuration: const Duration(milliseconds: 200),
        );
}

class ScaleRoute extends PageRouteBuilder {
  final Widget page;

  ScaleRoute({required this.page})
      : super(
          pageBuilder: (context, animation, secondaryAnimation) => page,
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            return ScaleTransition(scale: animation, child: child);
          },
          transitionDuration: const Duration(milliseconds: 250),
        );
}
```

### 2.2 底部弹出

```dart
Future<T?> showAppBottomSheet<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool isDismissible = true,
  bool enableDrag = true,
}) {
  return showModalBottomSheet<T>(
    context: context,
    isDismissible: isDismissible,
    enableDrag: enableDrag,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (context) => DraggableScrollableSheet(
      initialChildSize: 0.6,
      minChildSize: 0.3,
      maxChildSize: 0.95,
      builder: (context, scrollController) {
        return Container(
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: Column(
            children: [
              Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: Colors.grey[300],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              Expanded(child: builder(context)),
            ],
          ),
        );
      },
    ),
  );
}
```

## 3. 组件动画

### 3.1 按钮按压效果

```dart
class PressableButton extends StatefulWidget {
  final Widget child;
  final VoidCallback? onPressed;
  final Duration duration;

  const PressableButton({
    super.key,
    required this.child,
    this.onPressed,
    this.duration = const Duration(milliseconds: 100),
  });

  @override
  State<PressableButton> createState() => _PressableButtonState();
}

class _PressableButtonState extends State<PressableButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _scaleAnimation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: widget.duration,
    );
    _scaleAnimation = Tween<double>(begin: 1.0, end: 0.95).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onTapDown(TapDownDetails details) {
    _controller.forward();
  }

  void _onTapUp(TapUpDetails details) {
    _controller.reverse();
    widget.onPressed?.call();
  }

  void _onTapCancel() {
    _controller.reverse();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTapDown: _onTapDown,
      onTapUp: _onTapUp,
      onTapCancel: _onTapCancel,
      child: ScaleTransition(
        scale: _scaleAnimation,
        child: widget.child,
      ),
    );
  }
}
```

### 3.2 列表项入场动画

```dart
class AnimatedListItem extends StatefulWidget {
  final Widget child;
  final int index;
  final Duration delay;

  const AnimatedListItem({
    super.key,
    required this.child,
    required this.index,
    this.delay = const Duration(milliseconds: 50),
  });

  @override
  State<AnimatedListItem> createState() => _AnimatedListItemState();
}

class _AnimatedListItemState extends State<AnimatedListItem>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;
  late final Animation<Offset> _slide;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _opacity = Tween<double>(begin: 0, end: 1).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeOut),
    );
    _slide = Tween<Offset>(
      begin: const Offset(0, 0.2),
      end: Offset.zero,
    ).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic),
    );

    Future.delayed(widget.delay * widget.index, () {
      if (mounted) _controller.forward();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _opacity,
      child: SlideTransition(position: _slide, child: widget.child),
    );
  }
}
```

### 3.3 加载动画

```dart
class PulseLoading extends StatefulWidget {
  final Widget child;
  final bool loading;

  const PulseLoading({super.key, required this.child, this.loading = false});

  @override
  State<PulseLoading> createState() => _PulseLoadingState();
}

class _PulseLoadingState extends State<PulseLoading>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.loading) return widget.child;
    return FadeTransition(
      opacity: Tween<double>(begin: 0.5, end: 1).animate(_controller),
      child: widget.child,
    );
  }
}

class SuccessAnimation extends StatefulWidget {
  final VoidCallback? onComplete;

  const SuccessAnimation({super.key, this.onComplete});

  @override
  State<SuccessAnimation> createState() => _SuccessAnimationState();
}

class _SuccessAnimationState extends State<SuccessAnimation>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _scale;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 500),
    );
    _scale = CurvedAnimation(
      parent: _controller,
      curve: Curves.easeOutBack,
    );
    _controller.forward().then((_) {
      Future.delayed(const Duration(milliseconds: 500), () {
        widget.onComplete?.call();
      });
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ScaleTransition(
      scale: _scale,
      child: Container(
        width: 80,
        height: 80,
        decoration: const BoxDecoration(
          color: Colors.green,
          shape: BoxShape.circle,
        ),
        child: const Icon(Icons.check, color: Colors.white, size: 48),
      ),
    );
  }
}
```

## 4. 手势交互

### 4.1 滑动删除

```dart
class DismissibleListItem extends StatelessWidget {
  final Widget child;
  final String key;
  final VoidCallback onDismissed;
  final VoidCallback? onEdit;

  const DismissibleListItem({
    super.key,
    required this.child,
    required this.key,
    required this.onDismissed,
    this.onEdit,
  });

  @override
  Widget build(BuildContext context) {
    return Dismissible(
      key: ValueKey(key),
      direction: DismissDirection.horizontal,
      background: Container(
        color: Colors.green,
        alignment: Alignment.centerLeft,
        padding: const EdgeInsets.only(left: 20),
        child: const Icon(Icons.edit, color: Colors.white),
      ),
      secondaryBackground: Container(
        color: Colors.red,
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        child: const Icon(Icons.delete, color: Colors.white),
      ),
      confirmDismiss: (direction) async {
        if (direction == DismissDirection.startToEnd) {
          onEdit?.call();
          return false;
        }
        return await _showConfirmDialog(context);
      },
      onDismissed: (direction) {
        if (direction == DismissDirection.endToStart) {
          onDismissed();
        }
      },
      child: child,
    );
  }
}
```

### 4.2 下拉刷新

```dart
class PullToRefresh extends StatelessWidget {
  final Widget child;
  final Future<void> Function() onRefresh;

  const PullToRefresh({
    super.key,
    required this.child,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      color: AppColors.primary,
      backgroundColor: Colors.white,
      displacement: 40,
      strokeWidth: 2.5,
      onRefresh: onRefresh,
      child: child,
    );
  }
}
```

## 5. 动画性能优化

### 5.1 使用 RepaintBoundary

```dart
RepaintBoundary(
  child: ComplexAnimatedWidget(),
)
```

### 5.2 避免在动画中做重计算

```dart
// 不好：每次动画帧都计算
AnimatedBuilder(
  animation: animation,
  builder: (context, child) {
    final value = heavyCalculation(animation.value);
    return Text(value.toString());
  },
)

// 好：提前计算好
final computedValue = heavyCalculation(animation.value);
```

### 5.3 减少动画组件数量

```dart
// 不好：每个列表项都有独立的 AnimationController
ListView(
  children: items.map((item) => AnimatedItem(item: item)).toList(),
)

// 好：使用父级 AnimationController 统一控制
```

## 6. 可访问性

### 6.1 减少动态效果

```dart
class AccessibilityAnimations {
  static bool get reduceMotion =>
      WidgetsBinding.instance.platformDispatcher.accessibilityFeatures
          .reduceMotion;

  static Duration get adaptiveDuration =>
      reduceMotion ? Duration.zero : const Duration(milliseconds: 300);
}
```

## 7. 动画检查清单

- [ ] 动画时长符合规范
- [ ] 页面转场流畅
- [ ] 按钮有按压反馈
- [ ] 列表项入场动画
- [ ] 加载状态有动画
- [ ] 成功/失败有反馈动画
- [ ] 手势交互流畅
- [ ] 下拉刷新正常
- [ ] 60fps 不丢帧
- [ ] 支持减少动态效果
- [ ] 动画不影响性能
- [ ]  Hero 动画正确

---

*好的动画是无形的。它让交互更自然，让体验更愉悦，却不会让用户注意到它的存在。*
