# APP动画与交互动效设计

> 本文档是家健镜系统 APP 动画与交互动效的完整设计说明，覆盖页面转场、组件动画、手势交互、物理动画、性能优化。

## 1. 概述

### 1.1 设计目标

1. 动画流畅 60fps
2. 交互自然有反馈
3. 引导用户注意力
4. 增强产品质感
5. 不影响性能

### 1.2 动画类型

| 类型 | 说明 | 示例 |
| --- | --- | --- |
| 页面转场 | 页面切换动画 | 淡入淡出、滑动 |
| 组件动画 | 组件状态变化 | 加载、展开、收起 |
| 手势动画 | 跟随手势的动画 | 拖拽、滑动删除 |
| 物理动画 | 模拟物理效果 | 弹簧、阻尼 |
| 引导动画 | 功能引导 | 高亮、气泡 |

## 2. 页面转场

### 2.1 自定义转场

```dart
class FadeTransitionPage extends PageRouteBuilder {
  final Widget page;

  FadeTransitionPage({required this.page})
      : super(
          pageBuilder: (
            BuildContext context,
            Animation<double> animation,
            Animation<double> secondaryAnimation,
          ) =>
              page,
          transitionsBuilder: (
            BuildContext context,
            Animation<double> animation,
            Animation<double> secondaryAnimation,
            Widget child,
          ) =>
              FadeTransition(
            opacity: animation,
            child: child,
          ),
          transitionDuration: const Duration(milliseconds: 300),
        );
}

class SlideTransitionPage extends PageRouteBuilder {
  final Widget page;
  final SlideDirection direction;

  SlideTransitionPage({required this.page, this.direction = SlideDirection.left})
      : super(
          pageBuilder: (context, animation, secondaryAnimation) => page,
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            var begin = _getBeginOffset(direction);
            var end = Offset.zero;
            var curve = Curves.easeInOut;

            var tween = Tween(begin: begin, end: end).chain(CurveTween(curve: curve));

            return SlideTransition(
              position: animation.drive(tween),
              child: child,
            );
          },
          transitionDuration: const Duration(milliseconds: 300),
        );

  static Offset _getBeginOffset(SlideDirection direction) {
    switch (direction) {
      case SlideDirection.left:
        return Offset(1.0, 0.0);
      case SlideDirection.right:
        return Offset(-1.0, 0.0);
      case SlideDirection.up:
        return Offset(0.0, 1.0);
      case SlideDirection.down:
        return Offset(0.0, -1.0);
    }
  }
}

enum SlideDirection { left, right, up, down }
```

### 2.2 共享元素转场

```dart
class HeroAnimationPage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: GridView.builder(
        itemCount: 10,
        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 2),
        itemBuilder: (context, index) {
          return GestureDetector(
            onTap: () {
              Navigator.push(context, MaterialPageRoute(
                builder: (_) => DetailPage(id: index),
              ));
            },
            child: Hero(
              tag: 'image_$index',
              child: Image.network('https://example.com/image_$index.jpg'),
            ),
          );
        },
      ),
    );
  }
}

class DetailPage extends StatelessWidget {
  final int id;
  DetailPage({required this.id});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Hero(
          tag: 'image_$id',
          child: Image.network('https://example.com/image_$id.jpg'),
        ),
      ),
    );
  }
}
```

## 3. 组件动画

### 3.1 加载动画

```dart
class LoadingSpinner extends StatefulWidget {
  final double size;
  final Color color;

  LoadingSpinner({this.size = 40, this.color = Colors.blue});

  @override
  _LoadingSpinnerState createState() => _LoadingSpinnerState();
}

class _LoadingSpinnerState extends State<LoadingSpinner> with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(seconds: 1),
      vsync: this,
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RotationTransition(
      turns: _controller,
      child: CustomPaint(
        size: Size(widget.size, widget.size),
        painter: _SpinnerPainter(color: widget.color),
      ),
    );
  }
}

class _SpinnerPainter extends CustomPainter {
  final Color color;
  _SpinnerPainter({required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(
      Rect.fromLTWH(0, 0, size.width, size.height),
      -math.pi / 2,
      math.pi * 1.5,
      false,
      paint,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
```

### 3.2 展开收起动画

```dart
class ExpandableSection extends StatefulWidget {
  final String title;
  final Widget child;
  final bool initiallyExpanded;

  ExpandableSection({
    required this.title,
    required this.child,
    this.initiallyExpanded = false,
  });

  @override
  _ExpandableSectionState createState() => _ExpandableSectionState();
}

class _ExpandableSectionState extends State<ExpandableSection> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _heightFactor;
  bool _isExpanded = false;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(milliseconds: 300),
      vsync: this,
    );
    _heightFactor = _controller.drive(CurveTween(curve: Curves.easeInOut));
    _isExpanded = widget.initiallyExpanded;
    if (_isExpanded) _controller.value = 1.0;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _toggle() {
    setState(() {
      _isExpanded = !_isExpanded;
      if (_isExpanded) {
        _controller.forward();
      } else {
        _controller.reverse();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        GestureDetector(
          onTap: _toggle,
          child: Container(
            padding: EdgeInsets.all(16),
            child: Row(
              children: [
                Expanded(child: Text(widget.title, style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold))),
                RotationTransition(
                  turns: _controller.drive(Tween(begin: 0.0, end: 0.5)),
                  child: Icon(Icons.expand_more),
                ),
              ],
            ),
          ),
        ),
        ClipRect(
          child: Align(
            heightFactor: _heightFactor.value,
            child: widget.child,
          ),
        ),
      ],
    );
  }
}
```

### 3.3 数字滚动动画

```dart
class AnimatedCount extends StatefulWidget {
  final int target;
  final Duration duration;
  final TextStyle? style;

  AnimatedCount({required this.target, this.duration = const Duration(seconds: 1), this.style});

  @override
  _AnimatedCountState createState() => _AnimatedCountState();
}

class _AnimatedCountState extends State<AnimatedCount> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<int> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(duration: widget.duration, vsync: this);
    _animation = IntTween(begin: 0, end: widget.target).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeOut),
    );
    _controller.forward();
  }

  @override
  void didUpdateWidget(AnimatedCount oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.target != widget.target) {
      _animation = IntTween(begin: _animation.value, end: widget.target).animate(
        CurvedAnimation(parent: _controller, curve: Curves.easeOut),
      );
      _controller.reset();
      _controller.forward();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, child) {
        return Text(_animation.value.toString(), style: widget.style);
      },
    );
  }
}
```

## 4. 手势动画

### 4.1 滑动删除

```dart
class DismissibleCard extends StatelessWidget {
  final Widget child;
  final VoidCallback onDismiss;
  final String id;

  DismissibleCard({required this.child, required this.onDismiss, required this.id});

  @override
  Widget build(BuildContext context) {
    return Dismissible(
      key: Key(id),
      direction: DismissDirection.endToStart,
      background: Container(
        color: Colors.red,
        alignment: Alignment.centerRight,
        padding: EdgeInsets.only(right: 20),
        child: Icon(Icons.delete, color: Colors.white),
      ),
      onDismissed: (direction) => onDismiss(),
      child: child,
    );
  }
}
```

### 4.2 拖拽排序

```dart
class DraggableList extends StatefulWidget {
  final List<String> items;

  DraggableList({required this.items});

  @override
  _DraggableListState createState() => _DraggableListState();
}

class _DraggableListState extends State<DraggableList> {
  late List<String> _items;

  @override
  void initState() {
    super.initState();
    _items = List.from(widget.items);
  }

  @override
  Widget build(BuildContext context) {
    return ReorderableListView(
      children: [
        for (final item in _items)
          ListTile(
            key: ValueKey(item),
            title: Text(item),
            trailing: Icon(Icons.drag_handle),
          ),
      ],
      onReorder: (oldIndex, newIndex) {
        setState(() {
          if (newIndex > oldIndex) newIndex--;
          final item = _items.removeAt(oldIndex);
          _items.insert(newIndex, item);
        });
      },
    );
  }
}
```

## 5. 物理动画

### 5.1 弹簧动画

```dart
class SpringAnimation extends StatefulWidget {
  @override
  _SpringAnimationState createState() => _SpringAnimationState();
}

class _SpringAnimationState extends State<SpringAnimation> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: Duration(seconds: 2),
    );

    final spring = SpringDescription(
      mass: 1,
      stiffness: 100,
      damping: 10,
    );

    _animation = _controller.drive(SpringSimulation(
      spring,
      0,
      1,
      0,
    ));
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () {
        _controller.reset();
        _controller.forward();
      },
      child: AnimatedBuilder(
        animation: _animation,
        builder: (context, child) {
          return Transform.scale(
            scale: 0.5 + _animation.value * 0.5,
            child: child,
          );
        },
        child: Container(width: 100, height: 100, color: Colors.blue),
      ),
    );
  }
}
```

### 5.2 下拉刷新

```dart
class CustomRefreshIndicator extends StatelessWidget {
  final Widget child;
  final RefreshCallback onRefresh;

  CustomRefreshIndicator({required this.child, required this.onRefresh});

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: onRefresh,
      color: Colors.blue,
      backgroundColor: Colors.white,
      strokeWidth: 2.5,
      displacement: 40,
      child: child,
    );
  }
}
```

## 6. 动画性能优化

### 6.1 使用 RepaintBoundary

```dart
class OptimizedAnimation extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: _animation,
        builder: (context, child) {
          return CustomPaint(painter: _MyPainter(_animation.value));
        },
      ),
    );
  }
}
```

### 6.2 避免在 build 中创建对象

```dart
// 不好
Widget build(BuildContext context) {
  final controller = AnimationController(vsync: this); // 每次 build 都创建
  return ...;
}

// 好
late final AnimationController controller;

void initState() {
  controller = AnimationController(vsync: this);
}
```

### 6.3 使用 AnimatedWidget

```dart
class MyAnimatedWidget extends AnimatedWidget {
  MyAnimatedWidget({required Animation<double> animation})
      : super(listenable: animation);

  @override
  Widget build(BuildContext context) {
    final animation = listenable as Animation<double>;
    return Opacity(opacity: animation.value, child: ...);
  }
}
```

## 7. 动画设计规范

### 7.1 时长规范

| 动画类型 | 时长 |
| --- | --- |
| 微交互 | 100-200ms |
| 组件状态变化 | 200-300ms |
| 页面转场 | 300-400ms |
| 引导动画 | 500-1000ms |
| 加载动画 | 循环 1-2s |

### 7.2 缓动函数

| 效果 | 曲线 |
| --- | --- |
| 标准 | Curves.easeInOut |
| 进入 | Curves.easeOut |
| 退出 | Curves.easeIn |
| 弹性 | Curves.elasticOut |
| 回弹 | Curves.bounceOut |

## 8. 动画检查清单

- [ ] 页面转场
- [ ] 共享元素转场
- [ ] 加载动画
- [ ] 展开收起
- [ ] 数字滚动
- [ ] 滑动删除
- [ ] 拖拽排序
- [ ] 弹簧动画
- [ ] 下拉刷新
- [ ] 性能优化
- [ ] 时长规范
- [ ] 缓动函数

---

*精致的动画是产品质感的体现。流畅自然、恰到好处，让每一次交互都愉悦。*
