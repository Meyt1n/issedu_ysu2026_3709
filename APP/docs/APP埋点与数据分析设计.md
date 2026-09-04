# APP埋点与数据分析设计

> 本文档是家健镜系统 APP 埋点与数据分析的完整设计说明，覆盖埋点规范、数据采集、分析指标、数据应用。

## 1. 埋点概述

### 1.1 设计目标

1. 数据驱动：基于数据做决策
2. 用户洞察：了解用户行为
3. 产品优化：发现改进机会
4. 效果评估：衡量功能效果
5. 隐私合规：符合数据保护法规

### 1.2 埋点类型

| 类型 | 说明 | 示例 |
| --- | --- | --- |
| 页面浏览 | 用户访问页面 | 进入药品列表页 |
| 点击事件 | 用户点击元素 | 点击添加药品按钮 |
| 业务事件 | 关键业务动作 | 添加药品成功 |
| 性能事件 | 性能指标 | 页面加载时间 |
| 异常事件 | 错误和异常 | 网络请求失败 |

## 2. 埋点规范

### 2.1 事件命名

```
{模块}_{动作}_{对象}

示例：
medicine_add_click
medicine_list_view
medicine_detail_view
risk_alert_click
chat_message_send
```

### 2.2 事件属性

```dart
class AnalyticsEvent {
  final String name;
  final Map<String, dynamic> properties;
  final DateTime timestamp;

  AnalyticsEvent({
    required this.name,
    this.properties = const {},
  }) : timestamp = DateTime.now();
}
```

### 2.3 公共属性

```dart
class CommonProperties {
  static Map<String, dynamic> get() {
    return {
      'user_id': UserManager.instance.userId,
      'household_id': UserManager.instance.householdId,
      'app_version': PackageInfo.version,
      'platform': Platform.isIOS ? 'ios' : 'android',
      'os_version': Platform.operatingSystemVersion,
      'device_model': DeviceInfo.model,
      'network_type': Connectivity().type,
      'session_id': SessionManager.instance.sessionId,
      'timestamp': DateTime.now().toIso8601String(),
    };
  }
}
```

## 3. 数据采集

### 3.1 埋点 SDK

```dart
class AnalyticsManager {
  static final AnalyticsManager _instance = AnalyticsManager._();
  factory AnalyticsManager() => _instance;
  AnalyticsManager._();

  final List<AnalyticsEvent> _eventQueue = [];
  bool _isUploading = false;

  Future<void> track(String eventName, {Map<String, dynamic>? properties}) async {
    final event = AnalyticsEvent(
      name: eventName,
      properties: {...?properties, ...CommonProperties.get()},
    );

    _eventQueue.add(event);

    // 批量上报
    if (_eventQueue.length >= 20) {
      await _upload();
    }
  }

  Future<void> _upload() async {
    if (_isUploading || _eventQueue.isEmpty) return;

    _isUploading = true;
    try {
      final events = List.from(_eventQueue);
      _eventQueue.clear();

      await ApiClient.post('/analytics/events', {
        'events': events.map((e) => e.toJson()).toList(),
      });
    } catch (e) {
      // 失败后重新入队
      _eventQueue.insertAll(0, events);
    } finally {
      _isUploading = false;
    }
  }

  // 定时上报
  void startTimer() {
    Timer.periodic(Duration(seconds: 30), (_) => _upload());
  }

  // App 退出时上报
  Future<void> flush() async {
    await _upload();
  }
}
```

### 3.2 页面浏览埋点

```dart
class AnalyticsRouteObserver extends RouteObserver<PageRoute> {
  @override
  void didPush(Route route, Route? previousRoute) {
    super.didPush(route, previousRoute);
    if (route is PageRoute) {
      final pageName = route.settings.name ?? 'unknown';
      AnalyticsManager().track('page_view', properties: {
        'page_name': pageName,
        'previous_page': previousRoute?.settings.name,
      });
    }
  }

  @override
  void didPop(Route route, Route? previousRoute) {
    super.didPop(route, previousRoute);
    if (previousRoute is PageRoute) {
      AnalyticsManager().track('page_view', properties: {
        'page_name': previousRoute.settings.name,
        'from': route.settings.name,
      });
    }
  }
}
```

### 3.3 点击埋点

```dart
class AnalyticsButton extends StatelessWidget {
  final String eventName;
  final Map<String, dynamic>? properties;
  final VoidCallback onPressed;
  final Widget child;

  AnalyticsButton({
    required this.eventName,
    required this.onPressed,
    required this.child,
    this.properties,
  });

  @override
  Widget build(BuildContext context) {
    return ElevatedButton(
      onPressed: () {
        AnalyticsManager().track(eventName, properties: properties);
        onPressed();
      },
      child: child,
    );
  }
}
```

## 4. 核心指标

### 4.1 用户指标

| 指标 | 说明 | 计算方式 |
| --- | --- | --- |
| DAU | 日活跃用户 | 每日去重用户数 |
| MAU | 月活跃用户 | 每月去重用户数 |
| 留存率 | 次日/7日/30日留存 | 新增用户中后续回访比例 |
| 用户时长 | 平均使用时长 | 总时长 / 活跃用户数 |
| 启动次数 | 平均启动次数 | 总启动次数 / 活跃用户数 |

### 4.2 功能指标

| 功能 | 核心指标 |
| --- | --- |
| 药品管理 | 药品录入数、人均药品数、用药计划设置率 |
| 用药提醒 | 提醒发送数、提醒点击率、服药依从率 |
| 健康风险 | 风险识别数、风险处理率、风险确认率 |
| 健康助手 | 对话次数、人均对话数、满意度评分 |
| 视觉识别 | 识别次数、识别成功率、人工修正率 |

### 4.3 转化漏斗

```
启动 APP
    ↓ (85%)
进入首页
    ↓ (70%)
浏览功能
    ↓ (50%)
使用核心功能
    ↓ (60%)
完成关键动作
    ↓ (40%)
次日留存
```

## 5. 数据分析

### 5.1 留存分析

```sql
-- 次日留存计算
WITH new_users AS (
  SELECT user_id, DATE(MIN(event_time)) as install_date
  FROM events
  WHERE event_name = 'app_install'
  GROUP BY user_id
),
retention AS (
  SELECT
    n.install_date,
    COUNT(DISTINCT n.user_id) as new_count,
    COUNT(DISTINCT CASE WHEN e.event_time::date = n.install_date + 1 THEN e.user_id END) as d1_retained
  FROM new_users n
  LEFT JOIN events e ON n.user_id = e.user_id
  GROUP BY n.install_date
)
SELECT install_date, new_count, d1_retained,
       ROUND(d1_retained::float / new_count * 100, 2) as d1_retention_rate
FROM retention;
```

### 5.2 漏斗分析

```sql
-- 用药管理转化漏斗
SELECT
  'view_medicine_list' as step,
  COUNT(DISTINCT user_id) as users
FROM events WHERE event_name = 'medicine_list_view'
UNION ALL
SELECT
  'click_add_medicine',
  COUNT(DISTINCT user_id)
FROM events WHERE event_name = 'medicine_add_click'
UNION ALL
SELECT
  'medicine_add_success',
  COUNT(DISTINCT user_id)
FROM events WHERE event_name = 'medicine_add_success';
```

### 5.3 用户分群

```dart
class UserSegmentation {
  // 按活跃度分群
  static String getActivitySegment(int daysActive) {
    if (daysActive >= 25) return 'highly_active';
    if (daysActive >= 10) return 'moderately_active';
    if (daysActive >= 3) return 'lightly_active';
    return 'inactive';
  }

  // 按功能使用分群
  static String getFeatureSegment(Set<String> usedFeatures) {
    if (usedFeatures.containsAll(['medicine', 'risk', 'chat'])) {
      return 'power_user';
    }
    if (usedFeatures.contains('medicine')) {
      return 'medicine_only';
    }
    return 'casual';
  }
}
```

## 6. 数据应用

### 6.1 A/B 测试

```dart
class ABTestManager {
  static final Map<String, String> _experiments = {};

  static Future<void> init() async {
    // 从服务端获取实验配置
    final config = await ApiClient.get('/ab-test/config');
    _experiments.addAll(config);
  }

  static String getVariant(String experimentName) {
    return _experiments[experimentName] ?? 'control';
  }

  static bool isInGroup(String experimentName, String group) {
    return getVariant(experimentName) == group;
  }
}
```

### 6.2 智能推荐

基于用户行为数据，推荐相关功能和内容。

### 6.3 产品决策

- 功能优先级：基于使用率和留存影响
- UI 优化：基于点击热力图
- 流程优化：基于漏斗分析

## 7. 隐私保护

### 7.1 数据脱敏

- 不收集敏感健康数据
- 用户 ID 匿名化
- 数据聚合后上报

### 7.2 用户授权

```dart
class AnalyticsConsent {
  static Future<bool> requestConsent() async {
    // 显示隐私政策
    // 用户同意后才开始采集
  }

  static Future<void> optOut() async {
    // 用户退出数据采集
    AnalyticsManager().enabled = false;
  }
}
```

## 8. 埋点检查清单

- [ ] 事件命名规范
- [ ] 公共属性
- [ ] 页面浏览埋点
- [ ] 点击事件埋点
- [ ] 业务事件埋点
- [ ] 性能事件埋点
- [ ] 批量上报
- [ ] 离线缓存
- [ ] 核心指标定义
- [ ] 留存分析
- [ ] 漏斗分析
- [ ] A/B 测试
- [ ] 数据脱敏
- [ ] 用户授权

---

*数据是产品的眼睛。全面、准确的数据分析，让产品决策有据可依。*
