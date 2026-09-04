# APP推送通知服务设计

> 本文档是家健镜系统 APP 推送通知服务的完整设计说明，覆盖推送渠道、通知样式、推送策略、用户分组、效果分析。

## 1. 概述

### 1.1 设计目标

1. 推送送达率 > 95%
2. 推送延迟 < 5 秒
3. 用户可配置
4. 支持多渠道
5. 效果可追踪

### 1.2 推送渠道

| 渠道 | 平台 | 到达率 |
| --- | --- | --- |
| APNs | iOS | 高 |
| FCM | Android | 高 |
| 华为推送 | 华为 | 高 |
| 小米推送 | 小米 | 高 |
| OPPO 推送 | OPPO | 高 |
| vivo 推送 | vivo | 高 |
| 短信 | 全平台 | 最高 |

## 2. 推送服务架构

### 2.1 服务端架构

```python
class PushService:
    def __init__(self):
        self.providers = {
            'ios': APNsProvider(),
            'android_fcm': FCMProvider(),
            'android_huawei': HuaweiProvider(),
            'android_xiaomi': XiaomiProvider(),
            'android_oppo': OppoProvider(),
            'android_vivo': VivoProvider(),
        }

    async def send_push(self, user_id: str, title: str, body: str, data: dict = None):
        # 获取用户设备
        devices = await self._get_user_devices(user_id)

        for device in devices:
            provider = self._get_provider(device.platform)
            try:
                await provider.send(device.token, title, body, data)
                await self._record_success(user_id, device.platform)
            except Exception as e:
                await self._record_failure(user_id, device.platform, str(e))

    def _get_provider(self, platform: str):
        if platform == 'ios':
            return self.providers['ios']
        elif platform.startswith('android'):
            # 根据厂商选择推送服务
            return self.providers.get(f'android_{self._get_brand(platform)}', self.providers['android_fcm'])
```

### 2.2 推送网关

```python
class PushGateway:
    def __init__(self):
        self.rate_limiter = RateLimiter(max_requests=1000, per_seconds=1)
        self.queue = asyncio.Queue()

    async def enqueue(self, push_request: PushRequest):
        await self.queue.put(push_request)

    async def process_queue(self):
        while True:
            request = await self.queue.get()
            async with self.rate_limiter:
                await self._send(request)
            self.queue.task_done()

    async def _send(self, request: PushRequest):
        # 发送推送
        pass
```

## 3. 通知样式

### 3.1 普通通知

```dart
class NotificationHelper {
  static Future<void> showNormalNotification({
    required int id,
    required String title,
    required String body,
    String? payload,
  }) async {
    const androidDetails = AndroidNotificationDetails(
      'default_channel',
      '默认通知',
      channelDescription: '默认通知渠道',
      importance: Importance.max,
      priority: Priority.high,
    );

    const iosDetails = DarwinNotificationDetails();

    await flutterLocalNotificationsPlugin.show(
      id,
      title,
      body,
      const NotificationDetails(android: androidDetails, iOS: iosDetails),
      payload: payload,
    );
  }
}
```

### 3.2 用药提醒通知

```dart
class MedicationNotification {
  static Future<void> showReminder({
    required String medicineId,
    required String medicineName,
    required String dosage,
    required DateTime time,
  }) async {
    const androidDetails = AndroidNotificationDetails(
      'medication_channel',
      '用药提醒',
      channelDescription: '用药时间提醒',
      importance: Importance.max,
      priority: Priority.high,
      fullScreenIntent: true,
      actions: [
        AndroidNotificationAction('taken', '已服药'),
        AndroidNotificationAction('snooze', '稍后提醒'),
        AndroidNotificationAction('skip', '跳过'),
      ],
    );

    await flutterLocalNotificationsPlugin.show(
      medicineId.hashCode,
      '用药提醒',
      '该吃 $medicineName 了，剂量：$dosage',
      const NotificationDetails(android: androidDetails),
      payload: jsonEncode({'type': 'medication', 'id': medicineId}),
    );
  }
}
```

### 3.3 健康预警通知

```dart
class HealthAlertNotification {
  static Future<void> showAlert({
    required String alertType,
    required String title,
    required String message,
    required AlertLevel level,
  }) async {
    final channelId = level == AlertLevel.critical ? 'critical_alerts' : 'health_alerts';

    AndroidNotificationDetails androidDetails = AndroidNotificationDetails(
      channelId,
      level == AlertLevel.critical ? '紧急预警' : '健康预警',
      importance: level == AlertLevel.critical ? Importance.max : Importance.high,
      priority: level == AlertLevel.critical ? Priority.max : Priority.high,
      color: level == AlertLevel.critical ? Colors.red : Colors.orange,
    );

    await flutterLocalNotificationsPlugin.show(
      alertType.hashCode,
      title,
      message,
      NotificationDetails(android: androidDetails),
    );
  }
}
```

### 3.4 大文本通知

```dart
class BigTextNotification {
  static Future<void> showBigText({
    required int id,
    required String title,
    required String bigText,
    String? summary,
  }) async {
    final bigTextStyleInformation = BigTextStyleInformation(
      bigText,
      htmlFormatBigText: true,
      contentTitle: title,
      summaryText: summary,
    );

    final androidDetails = AndroidNotificationDetails(
      'big_text_channel',
      '大文本通知',
      styleInformation: bigTextStyleInformation,
    );

    await flutterLocalNotificationsPlugin.show(
      id,
      title,
      bigText,
      NotificationDetails(android: androidDetails),
    );
  }
}
```

## 4. 推送策略

### 4.1 智能推送时间

```python
class SmartPushScheduler:
    def __init__(self):
        self.user_activity_patterns = {}

    def get_best_push_time(self, user_id: str) -> datetime:
        # 分析用户活跃时间
        pattern = self.user_activity_patterns.get(user_id)
        if pattern:
            # 在用户最活跃的时间段推送
            return self._find_active_window(pattern)
        else:
            # 默认在白天推送
            now = datetime.now()
            if now.hour < 9:
                return now.replace(hour=9, minute=0, second=0)
            elif now.hour > 21:
                return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0)
            return now

    def _find_active_window(self, pattern: dict) -> datetime:
        # 找到用户最活跃的小时
        active_hours = sorted(pattern.items(), key=lambda x: x[1], reverse=True)
        best_hour = active_hours[0][0]
        now = datetime.now()
        return now.replace(hour=best_hour, minute=0, second=0)
```

### 4.2 推送频率控制

```python
class PushFrequencyController:
    def __init__(self, max_per_day: int = 10, min_interval_minutes: int = 5):
        self.max_per_day = max_per_day
        self.min_interval = timedelta(minutes=min_interval_minutes)
        self.user_push_log = {}

    async def can_push(self, user_id: str, push_type: str) -> tuple[bool, str]:
        today_pushes = self._get_today_pushes(user_id)

        # 检查每日上限
        if len(today_pushes) >= self.max_per_day:
            return False, "今日推送已达上限"

        # 检查最小间隔
        if today_pushes:
            last_push = today_pushes[-1]
            if datetime.now() - last_push.time < self.min_interval:
                return False, "推送间隔太短"

        # 检查免打扰
        if await self._is_dnd_time(user_id):
            return False, "用户免打扰时间"

        return True, ""

    def _get_today_pushes(self, user_id: str) -> list:
        today = datetime.now().date()
        return [p for p in self.user_push_log.get(user_id, []) if p.time.date() == today]
```

### 4.3 用户分组推送

```python
class UserSegmentation:
    def __init__(self):
        self.segments = {}

    def create_segment(self, name: str, conditions: list):
        self.segments[name] = conditions

    async def get_users_in_segment(self, segment_name: str) -> list[str]:
        conditions = self.segments.get(segment_name)
        if not conditions:
            return []

        # 根据条件筛选用户
        users = await self._query_users(conditions)
        return [user.id for user in users]

    async def push_to_segment(self, segment_name: str, title: str, body: str):
        user_ids = await self.get_users_in_segment(segment_name)
        for user_id in user_ids:
            await push_service.send_push(user_id, title, body)
```

## 5. 通知渠道管理

### 5.1 Android 渠道

```dart
class NotificationChannelManager {
  static Future<void> createChannels() async {
    const channels = [
      AndroidNotificationChannel(
        'medication_channel',
        '用药提醒',
        description: '用药时间提醒，高优先级',
        importance: Importance.max,
      ),
      AndroidNotificationChannel(
        'health_alerts',
        '健康预警',
        description: '健康数据异常预警',
        importance: Importance.high,
      ),
      AndroidNotificationChannel(
        'critical_alerts',
        '紧急预警',
        description: '紧急健康预警，全屏提醒',
        importance: Importance.max,
      ),
      AndroidNotificationChannel(
        'default_channel',
        '默认通知',
        description: '其他通知',
        importance: Importance.defaultImportance,
      ),
      AndroidNotificationChannel(
        'promo_channel',
        '活动推广',
        description: '营销活动通知',
        importance: Importance.low,
      ),
    ];

    for (final channel in channels) {
      await flutterLocalNotificationsPlugin
          .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
          ?.createNotificationChannel(channel);
    }
  }
}
```

### 5.2 iOS 通知类别

```dart
class IOSNotificationCategories {
  static Future<void> setupCategories() async {
    const medicationCategory = DarwinNotificationCategory(
      'medication_reminder',
      actions: [
        DarwinNotificationAction.plain('taken', '已服药'),
        DarwinNotificationAction.plain('snooze', '稍后提醒'),
        DarwinNotificationAction.plain('skip', '跳过', options: {DarwinNotificationActionOption.destructive}),
      ],
    );

    await flutterLocalNotificationsPlugin
        .resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>()
        ?.setNotificationCategories([medicationCategory]);
  }
}
```

## 6. 推送效果分析

### 6.1 推送指标

```python
class PushAnalytics:
    def __init__(self):
        self.metrics = {
            'sent': 0,
            'delivered': 0,
            'opened': 0,
            'dismissed': 0,
        }

    def record_sent(self, user_id: str, push_id: str):
        self.metrics['sent'] += 1
        # 记录到数据库

    def record_delivered(self, user_id: str, push_id: str):
        self.metrics['delivered'] += 1

    def record_opened(self, user_id: str, push_id: str):
        self.metrics['opened'] += 1

    def get_rates(self) -> dict:
        sent = self.metrics['sent']
        return {
            'delivery_rate': self.metrics['delivered'] / sent if sent else 0,
            'open_rate': self.metrics['opened'] / sent if sent else 0,
            'dismiss_rate': self.metrics['dismissed'] / sent if sent else 0,
        }
```

### 6.2 A/B 测试

```python
class PushABTest:
    def __init__(self):
        self.experiments = {}

    def create_experiment(self, name: str, variants: list):
        self.experiments[name] = {
            'variants': variants,
            'results': {v['id']: {'sent': 0, 'opened': 0} for v in variants},
        }

    def assign_variant(self, user_id: str, experiment: str) -> dict:
        exp = self.experiments[experiment]
        # 基于用户 ID 哈希分配
        variant_index = hash(user_id) % len(exp['variants'])
        return exp['variants'][variant_index]

    def record_result(self, experiment: str, variant_id: str, opened: bool):
        exp = self.experiments[experiment]
        exp['results'][variant_id]['sent'] += 1
        if opened:
            exp['results'][variant_id]['opened'] += 1

    def get_winner(self, experiment: str) -> str:
        exp = self.experiments[experiment]
        best_variant = max(
            exp['results'].items(),
            key=lambda x: x[1]['opened'] / x[1]['sent'] if x[1]['sent'] else 0,
        )
        return best_variant[0]
```

## 7. 推送检查清单

- [ ] 推送服务架构
- [ ] 多渠道支持
- [ ] 普通通知
- [ ] 用药提醒
- [ ] 健康预警
- [ ] 大文本通知
- [ ] 智能推送时间
- [ ] 频率控制
- [ ] 用户分组
- [ ] 通知渠道
- [ ] 效果分析
- [ ] A/B 测试

---

*精准的推送是用户关怀的延伸。多渠道触达、智能调度、效果追踪，让每条通知都有价值。*
