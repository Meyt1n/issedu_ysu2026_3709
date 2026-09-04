# APP推送通知与消息中心设计

> 本文档是家健镜系统 APP 推送通知与消息中心的完整设计说明，覆盖推送通道、通知类型、消息中心、通知管理、用户偏好。

## 1. 概述

### 1.1 设计目标

1. 通知送达率 > 95%
2. 通知延迟 < 30 秒
3. 支持多通道推送
4. 用户可自定义通知偏好
5. 不打扰用户休息

### 1.2 通知类型

| 类型 | 说明 | 优先级 | 通道 |
| --- | --- | --- | --- |
| 用药提醒 | 到点提醒服药 | 高 | 推送+短信 |
| 健康预警 | 健康数据异常 | 高 | 推送+短信 |
| 问诊消息 | 医生回复消息 | 中 | 推送 |
| 订单通知 | 订单状态变更 | 中 | 推送 |
| 社区互动 | 点赞评论关注 | 低 | 推送 |
| 系统公告 | 官方通知 | 中 | 推送 |
| 营销推广 | 活动优惠 | 低 | 推送 |

## 2. 推送架构

### 2.1 多通道推送

```
后端服务
    ↓
推送服务（统一调度）
    ├── FCM（Android 海外）
    ├── APNs（iOS）
    ├── 华为推送
    ├── 小米推送
    ├── OPPO 推送
    ├── vivo 推送
    └── 短信通道（备用）
```

### 2.2 推送服务

```python
class PushNotificationService:
    def __init__(self):
        self.channels = {
            'fcm': FCMChannel(),
            'apns': APNsChannel(),
            'huawei': HuaweiChannel(),
            'xiaomi': XiaomiChannel(),
        }

    async def send_notification(
        self,
        user_id: str,
        title: str,
        body: str,
        data: dict = None,
        priority: str = 'normal',
    ):
        # 获取用户设备信息
        devices = await self._get_user_devices(user_id)

        results = []
        for device in devices:
            channel = self.channels.get(device.push_channel)
            if channel:
                result = await channel.send(
                    token=device.push_token,
                    title=title,
                    body=body,
                    data=data or {},
                    priority=priority,
                )
                results.append(result)

        # 记录推送日志
        await self._log_push(user_id, title, body, results)

        return results

    async def _get_user_devices(self, user_id: str) -> list[Device]:
        return await device_repository.get_active_devices(user_id)
```

### 2.3 设备注册

```dart
class PushTokenManager {
  static Future<void> init() async {
    // 获取推送 Token
    String? token = await FirebaseMessaging.instance.getToken();
    if (token != null) {
      await _registerToken(token);
    }

    // 监听 Token 刷新
    FirebaseMessaging.instance.onTokenRefresh.listen((newToken) {
      _registerToken(newToken);
    });
  }

  static Future<void> _registerToken(String token) async {
    final deviceInfo = await DeviceInfoPlugin().deviceInfo;
    await apiService.registerPushToken(
      token: token,
      deviceId: deviceInfo.id,
      platform: Platform.isIOS ? 'ios' : 'android',
      manufacturer: deviceInfo.manufacturer,
    );
  }
}
```

## 3. 通知处理

### 3.1 前台通知

```dart
class NotificationHandler {
  static Future<void> init() async {
    // iOS 前台通知设置
    await FirebaseMessaging.instance.setForegroundNotificationPresentationOptions(
      alert: true,
      badge: true,
      sound: true,
    );

    // 监听前台消息
    FirebaseMessaging.onMessage.listen((RemoteMessage message) {
      _handleForegroundMessage(message);
    });

    // 监听通知点击
    FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
      _handleNotificationTap(message);
    });
  }

  static void _handleForegroundMessage(RemoteMessage message) {
    // 显示本地通知
    FlutterLocalNotificationsPlugin().show(
      message.notification.hashCode,
      message.notification?.title,
      message.notification?.body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          'health_channel',
          '健康提醒',
          importance: Importance.high,
          priority: Priority.high,
        ),
        iOS: DarwinNotificationDetails(),
      ),
      payload: jsonEncode(message.data),
    );
  }

  static void _handleNotificationTap(RemoteMessage message) {
    final type = message.data['type'];
    switch (type) {
      case 'medicine_reminder':
        navigatorKey.currentState?.pushNamed('/medicine');
        break;
      case 'consultation':
        navigatorKey.currentState?.pushNamed('/consultation');
        break;
      case 'order':
        navigatorKey.currentState?.pushNamed('/orders');
        break;
    }
  }
}
```

### 3.2 通知渠道

```dart
class NotificationChannels {
  static const String medicine = 'medicine_reminder';
  static const String health = 'health_alert';
  static const String consultation = 'consultation';
  static const String order = 'order';
  static const String community = 'community';
  static const String system = 'system';

  static Future<void> createChannels() async {
    final plugin = FlutterLocalNotificationsPlugin();

    await plugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(
      AndroidNotificationChannel(
        medicine,
        '用药提醒',
        description: '用药时间到点提醒',
        importance: Importance.high,
        priority: Priority.high,
        enableVibration: true,
      ),
    );

    await plugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(
      AndroidNotificationChannel(
        health,
        '健康预警',
        description: '健康数据异常预警',
        importance: Importance.max,
        priority: Priority.max,
        enableVibration: true,
      ),
    );
  }
}
```

## 4. 消息中心

### 4.1 消息列表

```dart
class MessageCenterPage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        appBar: AppBar(
          title: Text('消息中心'),
          bottom: TabBar(
            tabs: [
              Tab(text: '全部'),
              Tab(text: '提醒'),
              Tab(text: '互动'),
              Tab(text: '系统'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            MessageList(type: 'all'),
            MessageList(type: 'reminder'),
            MessageList(type: 'interaction'),
            MessageList(type: 'system'),
          ],
        ),
      ),
    );
  }
}
```

### 4.2 消息数据模型

```dart
class AppMessage {
  final String id;
  final String type;
  final String title;
  final String content;
  final Map<String, dynamic>? data;
  final bool isRead;
  final DateTime createdAt;

  AppMessage({
    required this.id,
    required this.type,
    required this.title,
    required this.content,
    this.data,
    this.isRead = false,
    required this.createdAt,
  });
}
```

### 4.3 未读计数

```dart
class UnreadBadge extends StatelessWidget {
  final int count;
  final Widget child;

  UnreadBadge({required this.count, required this.child});

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        child,
        if (count > 0)
          Positioned(
            right: 0,
            top: 0,
            child: Container(
              padding: EdgeInsets.all(2),
              decoration: BoxDecoration(
                color: Colors.red,
                borderRadius: BorderRadius.circular(10),
              ),
              constraints: BoxConstraints(minWidth: 16, minHeight: 16),
              child: Text(
                count > 99 ? '99+' : '$count',
                style: TextStyle(color: Colors.white, fontSize: 10),
                textAlign: TextAlign.center,
              ),
            ),
          ),
      ],
    );
  }
}
```

## 5. 用户偏好

### 5.1 通知设置

```dart
class NotificationSettings {
  bool medicineReminder = true;
  bool healthAlert = true;
  bool consultation = true;
  bool orderNotification = true;
  bool communityInteraction = true;
  bool systemAnnouncement = true;
  bool marketing = false;

  // 免打扰时段
  bool doNotDisturb = false;
  TimeOfDay? dndStart;
  TimeOfDay? dndEnd;

  // 振动
  bool vibration = true;

  // 声音
  bool sound = true;
}
```

### 5.2 免打扰逻辑

```python
class DoNotDisturbService:
    @staticmethod
    def should_send(user_preferences: dict, current_time: datetime) -> bool:
        if not user_preferences.get('do_not_disturb', False):
            return True

        dnd_start = user_preferences.get('dnd_start')
        dnd_end = user_preferences.get('dnd_end')

        if not dnd_start or not dnd_end:
            return True

        current_minutes = current_time.hour * 60 + current_time.minute
        start_minutes = dnd_start['hour'] * 60 + dnd_start['minute']
        end_minutes = dnd_end['hour'] * 60 + dnd_end['minute']

        # 处理跨天情况
        if start_minutes <= end_minutes:
            in_dnd = start_minutes <= current_minutes < end_minutes
        else:
            in_dnd = current_minutes >= start_minutes or current_minutes < end_minutes

        return not in_dnd
```

## 6. 推送检查清单

- [ ] 多通道推送
- [ ] 设备注册
- [ ] Token 刷新
- [ ] 前台通知
- [ ] 通知点击
- [ ] 通知渠道
- [ ] 消息中心
- [ ] 未读计数
- [ ] 通知设置
- [ ] 免打扰
- [ ] 推送日志
- [ ] 送达统计

---

*及时的通知让健康管理不遗漏。多通道推送、消息中心、用户偏好，让每一条提醒都恰到好处。*
