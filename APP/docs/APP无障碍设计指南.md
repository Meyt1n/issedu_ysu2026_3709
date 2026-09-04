# APP无障碍设计指南

> 本文档是家健镜系统 APP 无障碍设计的完整指南，覆盖视觉无障碍、听觉无障碍、运动无障碍、认知无障碍。

## 1. 概述

### 1.1 设计目标

1. 可感知：信息和界面组件必须以用户可感知的方式呈现
2. 可操作：界面组件和导航必须可操作
3. 可理解：信息和用户界面操作必须可理解
4. 健壮性：内容必须能被各种辅助技术可靠解读

### 1.2 无障碍标准

| 标准 | 说明 |
| --- | --- |
| WCAG 2.1 AA | Web 内容无障碍指南 |
| iOS Accessibility | Apple 无障碍规范 |
| Android Accessibility | Google 无障碍规范 |

## 2. 视觉无障碍

### 2.1 颜色对比度

```dart
// 颜色对比度检查
// 正常文本：对比度 >= 4.5:1
// 大文本：对比度 >= 3:1

class AppColors {
  // 好的对比度
  static const Color primary = Color(0xFF1565C0);  // 深蓝，白底对比度 7:1
  static const Color textPrimary = Color(0xFF212121);  // 深灰，对比度 16:1
  static const Color textSecondary = Color(0xFF757575);  // 中灰，对比度 4.6:1

  // 不好的对比度
  // static const Color textLight = Color(0xFFBDBDBD);  // 浅灰，对比度 2.8:1
}
```

### 2.2 字体缩放

```dart
// 支持系统字体缩放
class AccessibleText extends StatelessWidget {
  final String text;
  final double fontSize;

  AccessibleText({required this.text, this.fontSize = 16});

  @override
  Widget build(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    final scaledFontSize = fontSize * mediaQuery.textScaleFactor;

    return Text(
      text,
      style: TextStyle(fontSize: scaledFontSize),
    );
  }
}

// 最大字体限制
class MaxScaleText extends StatelessWidget {
  final String text;
  final double maxScale;

  MaxScaleText({required this.text, this.maxScale = 2.0});

  @override
  Widget build(BuildContext context) {
    final scale = MediaQuery.of(context).textScaleFactor.clamp(1.0, maxScale);
    return MediaQuery(
      data: MediaQuery.of(context).copyWith(textScaleFactor: scale),
      child: Text(text),
    );
  }
}
```

### 2.3 语义标签

```dart
// 为图标按钮添加语义标签
class AccessibleIconButton extends StatelessWidget {
  final IconData icon;
  final String semanticLabel;
  final VoidCallback onPressed;

  AccessibleIconButton({
    required this.icon,
    required this.semanticLabel,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: semanticLabel,
      button: true,
      child: IconButton(
        icon: Icon(icon),
        onPressed: onPressed,
      ),
    );
  }
}

// 使用示例
AccessibleIconButton(
  icon: Icons.add,
  semanticLabel: '添加药品',
  onPressed: () => _addMedicine(),
)
```

### 2.4 焦点管理

```dart
// 焦点顺序
class FocusOrder extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        TextField(
          autofocus: true,
          textInputAction: TextInputAction.next,
          decoration: InputDecoration(labelText: '药品名称'),
        ),
        TextField(
          textInputAction: TextInputAction.next,
          decoration: InputDecoration(labelText: '剂量'),
        ),
        TextField(
          textInputAction: TextInputAction.done,
          decoration: InputDecoration(labelText: '频率'),
        ),
      ],
    );
  }
}
```

## 3. 听觉无障碍

### 3.1 字幕和文字替代

```dart
// 视频字幕
class CaptionedVideo extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        VideoPlayer(),
        Positioned(
          bottom: 20,
          left: 20,
          right: 20,
          child: CaptionText(),  // 字幕组件
        ),
      ],
    );
  }
}

// 声音提示的视觉替代
class VisualAlert extends StatelessWidget {
  final String message;
  final bool isError;

  VisualAlert({required this.message, this.isError = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(16),
      color: isError ? Colors.red : Colors.green,
      child: Row(
        children: [
          Icon(isError ? Icons.error : Icons.check_circle),
          SizedBox(width: 8),
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}
```

## 4. 运动无障碍

### 4.1 触摸目标大小

```dart
// 最小触摸目标 44x44 (iOS) / 48x48 (Android)
class AccessibleButton extends StatelessWidget {
  final String label;
  final VoidCallback onPressed;

  AccessibleButton({required this.label, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 48,  // 最小高度
      child: ElevatedButton(
        onPressed: onPressed,
        child: Text(label),
      ),
    );
  }
}
```

### 4.2 手势替代

```dart
// 提供手势的按钮替代
class SwipeAlternative extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Dismissible(
          key: Key('item'),
          child: ListTile(title: Text('可滑动删除')),
        ),
        // 同时提供删除按钮
        IconButton(
          icon: Icon(Icons.delete),
          onPressed: () => _delete(),
        ),
      ],
    );
  }
}
```

### 4.3 减少动画

```dart
// 尊重减少动画设置
class RespectAnimationSetting extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final disableAnimations = MediaQuery.of(context).disableAnimations;

    return disableAnimations
        ? StaticContent()
        : AnimatedContent();
  }
}
```

## 5. 认知无障碍

### 5.1 简洁清晰

```dart
// 简单的语言
class SimpleInstructions extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '如何添加药品',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        SizedBox(height: 8),
        Text('1. 点击右下角的添加按钮'),
        Text('2. 输入药品名称和剂量'),
        Text('3. 设置用药时间'),
        Text('4. 点击保存'),
      ],
    );
  }
}
```

### 5.2 错误提示

```dart
// 清晰的错误提示
class ClearError extends StatelessWidget {
  final String error;

  ClearError({required this.error});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          error,
          style: TextStyle(color: Colors.red),
        ),
        SizedBox(height: 4),
        Text(
          '请检查输入后重试',
          style: TextStyle(color: Colors.grey),
        ),
      ],
    );
  }
}
```

## 6. 无障碍测试

### 6.1 测试工具

| 平台 | 工具 | 说明 |
| --- | --- | --- |
| iOS | Accessibility Inspector | 检查无障碍属性 |
| Android | Accessibility Scanner | 扫描无障碍问题 |
| Flutter | Semantics Debugger | 调试语义树 |

### 6.2 测试清单

- [ ] 颜色对比度达标
- [ ] 支持字体缩放
- [ ] 所有图片有语义标签
- [ ] 所有按钮可聚焦
- [ ] 焦点顺序合理
- [ ] 视频有字幕
- [ ] 声音有视觉替代
- [ ] 触摸目标足够大
- [ ] 手势有按钮替代
- [ ] 尊重减少动画设置
- [ ] 语言简洁清晰
- [ ] 错误提示明确

## 7. 无障碍检查清单

- [ ] 视觉无障碍
- [ ] 颜色对比度
- [ ] 字体缩放
- [ ] 语义标签
- [ ] 焦点管理
- [ ] 听觉无障碍
- [ ] 字幕
- [ ] 视觉替代
- [ ] 运动无障碍
- [ ] 触摸目标
- [ ] 手势替代
- [ ] 减少动画
- [ ] 认知无障碍
- [ ] 简洁语言
- [ ] 清晰错误
- [ ] 无障碍测试

---

*无障碍设计让每个人都能使用。包容的设计，让健康服务惠及所有人。*
