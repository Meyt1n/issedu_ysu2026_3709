# APP无障碍设计与适配

> 本文档是家健镜系统 APP 无障碍设计与适配的完整设计说明，覆盖视觉无障碍、听觉无障碍、运动无障碍、认知无障碍、测试验证。

## 1. 概述

### 1.1 设计目标

1. 符合 WCAG 2.1 AA 标准
2. 支持屏幕阅读器
3. 支持大字体
4. 支持高对比度
5. 操作方式多样化

### 1.2 无障碍类型

| 类型 | 障碍 | 适配方案 |
| --- | --- | --- |
| 视觉 | 低视力、色盲、全盲 | 大字体、高对比度、屏幕阅读器 |
| 听觉 | 听障 | 字幕、视觉提示 |
| 运动 | 肢体障碍 | 语音控制、简化操作 |
| 认知 | 认知障碍 | 简化界面、清晰引导 |

## 2. 视觉无障碍

### 2.1 字体缩放

```dart
class AccessibleText extends StatelessWidget {
  final String text;
  final double baseFontSize;
  final FontWeight? fontWeight;

  AccessibleText({
    required this.text,
    this.baseFontSize = 16,
    this.fontWeight,
  });

  @override
  Widget build(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    final textScaleFactor = mediaQuery.textScaleFactor.clamp(1.0, 2.0);

    return Text(
      text,
      style: TextStyle(
        fontSize: baseFontSize * textScaleFactor,
        fontWeight: fontWeight,
      ),
    );
  }
}
```

### 2.2 颜色对比度

```dart
class AccessibleColors {
  // 符合 WCAG AA 的颜色对
  static const Color primary = Color(0xFF1565C0);  // 深蓝
  static const Color onPrimary = Colors.white;
  static const Color secondary = Color(0xFF2E7D32); // 深绿
  static const Color onSecondary = Colors.white;
  static const Color error = Color(0xFFC62828);     // 深红
  static const Color onError = Colors.white;
  static const Color background = Color(0xFFFAFAFA);
  static const Color onBackground = Color(0xFF212121);
  static const Color surface = Colors.white;
  static const Color onSurface = Color(0xFF212121);

  // 高对比度模式
  static const Color highContrastBackground = Colors.black;
  static const Color highContrastText = Colors.white;
  static const Color highContrastPrimary = Color(0xFF90CAF9);
}
```

### 2.3 色盲友好

```dart
class ColorBlindFriendly {
  // 不依赖颜色区分状态
  static Widget statusIndicator(String status) {
    IconData icon;
    String label;
    Color color;

    switch (status) {
      case 'normal':
        icon = Icons.check_circle;
        label = '正常';
        color = Colors.green;
        break;
      case 'warning':
        icon = Icons.warning;
        label = '警告';
        color = Colors.orange;
        break;
      case 'critical':
        icon = Icons.error;
        label = '严重';
        color = Colors.red;
        break;
      default:
        icon = Icons.help;
        label = '未知';
        color = Colors.grey;
    }

    return Row(
      children: [
        Icon(icon, color: color),
        SizedBox(width: 8),
        Text(label),
      ],
    );
  }
}
```

## 3. 屏幕阅读器

### 3.1 Semantics

```dart
class AccessibleButton extends StatelessWidget {
  final String label;
  final String? hint;
  final VoidCallback onTap;
  final Widget child;

  AccessibleButton({
    required this.label,
    this.hint,
    required this.onTap,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: label,
      hint: hint,
      button: true,
      enabled: true,
      onTap: onTap,
      child: ExcludeSemantics(child: child),
    );
  }
}

// 使用
AccessibleButton(
  label: '确认服药',
  hint: '双击确认已服用药物',
  onTap: () => confirmMedication(),
  child: ElevatedButton(onPressed: () {}, child: Text('确认')),
)
```

### 3.2 动态内容公告

```dart
class AccessibleAnnouncement {
  static void announce(String message) {
    SemanticsService.announce(message, TextDirection.ltr);
  }
}

// 数据更新时公告
void updateHealthData() {
  // 更新数据
  AccessibleAnnouncement.announce('血压数据已更新，当前血压 120/80，正常');
}
```

### 3.3 焦点管理

```dart
class AccessibleFocusTraversal extends StatelessWidget {
  final Widget child;

  AccessibleFocusTraversal({required this.child});

  @override
  Widget build(BuildContext context) {
    return FocusTraversalGroup(
      policy: ReadingOrderTraversalPolicy(),
      child: child,
    );
  }
}
```

## 4. 听觉无障碍

### 4.1 字幕支持

```dart
class AccessibleVideoPlayer extends StatelessWidget {
  final String videoUrl;
  final String? subtitleUrl;

  AccessibleVideoPlayer({required this.videoUrl, this.subtitleUrl});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        VideoPlayer(url: videoUrl),
        if (subtitleUrl != null) SubtitleDisplay(url: subtitleUrl!),
      ],
    );
  }
}
```

### 4.2 视觉提示替代声音

```dart
class AccessibleAlert extends StatelessWidget {
  final String message;
  final AlertType type;

  AccessibleAlert({required this.message, required this.type});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _getBackgroundColor(),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: _getBorderColor(), width: 2),
      ),
      child: Row(
        children: [
          Icon(_getIcon(), color: _getIconColor()),
          SizedBox(width: 12),
          Expanded(child: Text(message)),
          // 振动反馈
          VibrationFeedback(type: type),
        ],
      ),
    );
  }
}
```

## 5. 运动无障碍

### 5.1 大点击区域

```dart
class AccessibleTapTarget extends StatelessWidget {
  final Widget child;
  final VoidCallback onTap;
  final double minSize;

  AccessibleTapTarget({
    required this.child,
    required this.onTap,
    this.minSize = 48,
  });

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: BoxConstraints(minWidth: minSize, minHeight: minSize),
      child: InkWell(onTap: onTap, child: Center(child: child)),
    );
  }
}
```

### 5.2 语音控制

```dart
class VoiceCommandHandler {
  final SpeechToText _speech = SpeechToText();

  Future<void> init() async {
    await _speech.initialize();
  }

  void startListening(void Function(String) onResult) {
    _speech.listen(onResult: (result) {
      onResult(result.recognizedWords);
    });
  }

  void stopListening() {
    _speech.stop();
  }

  // 命令解析
  void handleCommand(String command) {
    if (command.contains('服药') || command.contains('吃药')) {
      confirmMedication();
    } else if (command.contains('血压') || command.contains('测量')) {
      startMeasurement();
    } else if (command.contains('报告') || command.contains('查看')) {
      openReport();
    }
  }
}
```

## 6. 认知无障碍

### 6.1 简化界面

```dart
class SimpleMode {
  static bool isSimpleMode(BuildContext context) {
    return Provider.of<SettingsProvider>(context).simpleMode;
  }

  static Widget wrapIfSimple({required Widget complex, required Widget simple}) {
    return Builder(
      builder: (context) {
        return isSimpleMode(context) ? simple : complex;
      },
    );
  }
}
```

### 6.2 清晰引导

```dart
class StepByStepGuide extends StatelessWidget {
  final List<GuideStep> steps;
  final int currentStep;

  StepByStepGuide({required this.steps, required this.currentStep});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // 进度指示器
        Row(
          children: [
            for (int i = 0; i < steps.length; i++)
              StepIndicator(
                step: i + 1,
                isActive: i == currentStep,
                isCompleted: i < currentStep,
              ),
          ],
        ),
        SizedBox(height: 24),
        // 当前步骤内容
        steps[currentStep].content,
        SizedBox(height: 24),
        // 导航按钮
        Row(
          children: [
            if (currentStep > 0)
              OutlinedButton(onPressed: () => previousStep(), child: Text('上一步')),
            Spacer(),
            ElevatedButton(
              onPressed: () => nextStep(),
              child: Text(currentStep == steps.length - 1 ? '完成' : '下一步'),
            ),
          ],
        ),
      ],
    );
  }
}
```

## 7. 无障碍测试

### 7.1 自动化测试

```dart
void main() {
  testWidgets('所有按钮有语义标签', (WidgetTester tester) async {
    await tester.pumpWidget(MyApp());

    final buttons = find.byType(ElevatedButton);
    for (final button in buttons.evaluate()) {
      final semantics = tester.getSemantics(find.byWidget(button.widget));
      expect(semantics.label, isNotNull);
    }
  });

  testWidgets('文本对比度符合标准', (WidgetTester tester) async {
    // 检查颜色对比度
  });
}
```

### 7.2 手动测试清单

```markdown
## 无障碍测试清单

### 视觉
- [ ] 支持系统字体缩放
- [ ] 大字体下布局不溢出
- [ ] 颜色对比度 > 4.5:1
- [ ] 不依赖颜色传达信息
- [ ] 支持深色模式

### 屏幕阅读器
- [ ] 所有交互元素有标签
- [ ] 焦点顺序合理
- [ ] 动态内容有公告
- [ ] 图片有描述
- [ ] 表单有错误提示

### 听觉
- [ ] 视频有字幕
- [ ] 声音提示有视觉替代
- [ ] 重要信息不只用声音

### 运动
- [ ] 点击区域 >= 48dp
- [ ] 支持语音控制
- [ ] 操作可撤销
- [ ] 避免精确手势

### 认知
- [ ] 界面简洁清晰
- [ ] 有操作引导
- [ ] 错误提示明确
- [ ] 术语一致
```

## 8. 无障碍检查清单

- [ ] 字体缩放
- [ ] 颜色对比度
- [ ] 色盲友好
- [ ] 屏幕阅读器
- [ ] 动态公告
- [ ] 焦点管理
- [ ] 字幕支持
- [ ] 视觉提示
- [ ] 大点击区域
- [ ] 语音控制
- [ ] 简化界面
- [ ] 清晰引导

---

*无障碍设计让每个人都能使用。视觉、听觉、运动、认知，全方位适配，让健康管理无死角。*
