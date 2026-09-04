# APP推送通知设计

> 本文档是家健镜 APP 推送通知的完整设计说明，覆盖通知类型、本地通知、远程推送、通知渠道、用户偏好、深度集成。面向移动端开发者，作为推送实现的权威依据。

## 1. 推送概述

### 1.1 设计目标

1. **及时提醒**：用药提醒、风险告警实时到达
2. **不打扰**：尊重用户偏好，可自定义通知时间
3. **可操作**：通知支持直接操作（确认服药、查看详情）
4. **可靠送达**：多通道保障，离线消息不丢失
5. **隐私保护**：通知内容不泄露敏感健康信息

### 1.2 通知类型

| 类型 | 触发方式 | 说明 | 示例 |
| --- | --- | --- | --- |
| 用药提醒 | 本地定时 | 到点提醒服药 | "该服用阿莫西林了" |
| 风险告警 | 远程推送 | 健康风险实时通知 | "检测到过敏冲突" |
| 任务完成 | 远程推送 | 视觉识别完成 | "药品识别完成" |
| 聊天消息 | 远程推送 | 健康助手新消息 | "健康助手回复了您" |
| 家庭邀请 | 远程推送 | 邀请加入家庭 | "张三邀请您加入家庭" |
| 系统通知 | 远程推送 | 系统公告 | "系统将于今晚维护" |
| 每日总结 | 本地定时 | 每日健康总结 | "今日健康报告" |

## 2. 本地通知

### 2.1 本地通知服务

```dart
class LocalNotificationService {
  static final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();

  static const String channelId = 'homecare_notifications';
  static const String channelName = '家健镜通知';
  static const String channelDescription = '家健镜健康提醒和通知';

  static Future<void> init() async {
    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    );

    await _plugin.initialize(
      const InitializationSettings(
        android: androidSettings,
        iOS: iosSettings,
      ),
      onDidReceiveNotificationResponse: _onNotificationTap,
    );

    await _createChannel();
  }

  static Future<void> _createChannel() async {
    const channel = AndroidNotificationChannel(
      channelId,
      channelName,
      description: channelDescription,
      importance: Importance.high,
      priority: Priority.high,
      enableVibration: true,
      playSound: true,
    );
    await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(channel);
  }

  static Future<void> scheduleMedicationReminder({
    required int id,
    required String medicineName,
    required String dosage,
    required DateTime scheduledTime,
    required String memberId,
  }) async {
    await _plugin.zonedSchedule(
      id,
      '用药提醒',
      '该服用 $medicineName（$dosage）了',
      tz.TZDateTime.from(scheduledTime, tz.local),
      const NotificationDetails(
        android: AndroidNotificationDetails(
          channelId,
          channelName,
          channelDescription: channelDescription,
          importance: Importance.high,
          priority: Priority.high,
          actions: [
            AndroidNotificationAction('taken', '已服用'),
            AndroidNotificationAction('snooze', '稍后提醒'),
          ],
        ),
        iOS: DarwinNotificationDetails(
          presentAlert: true,
          presentBadge: true,
          presentSound: true,
        ),
      ),
      androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
      uiLocalNotificationDateInterpretation:
          UILocalNotificationDateInterpretation.absoluteTime,
      matchDateTimeComponents: DateTimeComponents.time,
      payload: 'medicine_reminder_$memberId',
    );
  }

  static Future<void> cancelNotification(int id) async {
    await _plugin.cancel(id);
  }

  static Future<void> cancelAll() async {
    await _plugin.cancelAll();
  }

  static void _onNotificationTap(NotificationResponse response) {
    final payload = response.payload;
    if (payload != null) {
      // 处理通知点击
      NotificationRouter.handle(payload, response.actionId);
    }
  }
}
```

### 2.2 用药提醒调度

```dart
class MedicationReminderScheduler {
  final LocalNotificationService _notificationService;

  MedicationReminderScheduler(this._notificationService);

  Future<void> scheduleForPlan(MedicationPlan plan) async {
    // 取消旧的提醒
    for (final reminder in plan.reminders) {
      await _notificationService.cancelNotification(reminder.notificationId);
    }

    // 安排新的提醒
    for (var i = 0; i < plan.times.length; i++) {
      final time = plan.times[i];
      final notificationId = _generateId(plan.id, i);

      await _notificationService.scheduleMedicationReminder(
        id: notificationId,
        medicineName: plan.medicineName,
        dosage: plan.dosage,
        scheduledTime: _nextInstanceOfTime(time),
        memberId: plan.memberId,
      );
    }
  }

  int _generateId(String planId, int index) {
    return (planId.hashCode + index) & 0x7fffffff;
  }

  DateTime _nextInstanceOfTime(TimeOfDay time) {
    final now = DateTime.now();
    var scheduled = DateTime(
      now.year,
      now.month,
      now.day,
      time.hour,
      time.minute,
    );
    if (scheduled.isBefore(now)) {
      scheduled = scheduled.add(const Duration(days: 1));
    }
    return scheduled;
  }
}
```

## 3. 远程推送

### 3.1 FCM 集成

```dart
class PushNotificationService {
  final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  final LocalNotificationService _localService;

  PushNotificationService(this._localService);

  Future<void> init() async {
    // 请求权限
    await _requestPermission();

    // 获取 Token
    final token = await _messaging.getToken();
    await _registerToken(token);

    // Token 刷新
    _messaging.onTokenRefresh.listen((newToken) {
      _registerToken(newToken);
    });

    // 前台消息
    FirebaseMessaging.onMessage.listen(_handleForegroundMessage);

    // 后台点击
    FirebaseMessaging.onMessageOpenedApp.listen(_handleMessageTap);

    // 终止状态点击
    final initialMessage = await _messaging.getInitialMessage();
    if (initialMessage != null) {
      _handleMessageTap(initialMessage);
    }
  }

  Future<void> _requestPermission() async {
    await _messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
      provisional: false,
    );
  }

  Future<void> _registerToken(String? token) async {
    if (token == null) return;
    await apiClient.post('/devices/register', data: {
      'token': token,
      'platform': Platform.isIOS ? 'ios' : 'android',
    });
  }

  void _handleForegroundMessage(RemoteMessage message) {
    // 前台时显示本地通知
    final notification = message.notification;
    if (notification != null) {
      _localService.showNotification(
        id: DateTime.now().millisecondsSinceEpoch ~/ 1000,
        title: notification.title ?? '通知',
        body: notification.body ?? '',
        payload: message.data['type'],
      );
    }
  }

  void _handleMessageTap(RemoteMessage message) {
    NotificationRouter.handlePush(message.data);
  }
}
```

### 3.2 通知渠道

```dart
class NotificationChannels {
  // 用药提醒 - 高优先级
  static const AndroidNotificationChannel medication = AndroidNotificationChannel(
    'medication_reminders',
    '用药提醒',
    description: '定时用药提醒通知',
    importance: Importance.high,
    priority: Priority.high,
    enableVibration: true,
    playSound: true,
  );

  // 风险告警 - 最高优先级
  static const AndroidNotificationChannel risk = AndroidNotificationChannel(
    'risk_alerts',
    '风险告警',
    description: '健康风险实时告警',
    importance: Importance.max,
    priority: Priority.max,
    enableVibration: true,
    playSound: true,
  );

  // 一般通知 - 默认优先级
  static const AndroidNotificationChannel general = AndroidNotificationChannel(
    'general_notifications',
    '一般通知',
    description: '系统通知和消息',
    importance: Importance.defaultImportance,
    priority: Priority.defaultPriority,
  );

  // 营销通知 - 低优先级
  static const AndroidNotificationChannel marketing = AndroidNotificationChannel(
    'marketing',
    '活动推广',
    description: '活动和推广通知',
    importance: Importance.low,
    priority: Priority.low,
  );
}
```

## 4. 通知操作

### 4.1 操作按钮

```dart
class NotificationActions {
  static const String actionTaken = 'taken';
  static const String actionSnooze = 'snooze';
  static const String actionAcknowledge = 'acknowledge';
  static const String actionView = 'view';

  static Future<void> handleAction(
    String actionId,
    String payload,
  ) async {
    switch (actionId) {
      case actionTaken:
        await _markMedicationTaken(payload);
        break;
      case actionSnooze:
        await _snoozeReminder(payload);
        break;
      case actionAcknowledge:
        await _acknowledgeRisk(payload);
        break;
      case actionView:
        NotificationRouter.handle(payload, null);
        break;
    }
  }

  static Future<void> _markMedicationTaken(String payload) async {
    final memberId = payload.replaceFirst('medicine_reminder_', '');
    await medicationService.recordDose(
      memberId: memberId,
      takenAt: DateTime.now(),
    );
  }

  static Future<void> _snoozeReminder(String payload) async {
    // 10 分钟后再次提醒
    final snoozeTime = DateTime.now().add(const Duration(minutes: 10));
    // 重新安排通知
  }
}
```

## 5. 用户偏好

### 5.1 通知设置

```dart
class NotificationSettings {
  bool medicationReminders = true;
  bool riskAlerts = true;
  bool chatMessages = true;
  bool familyInvitations = true;
  bool dailySummary = true;
  bool marketing = false;

  TimeOfDay quietHoursStart = const TimeOfDay(hour: 22, minute: 0);
  TimeOfDay quietHoursEnd = const TimeOfDay(hour: 8, minute: 0);
  bool enableQuietHours = false;

  Map<String, dynamic> toJson() => {
        'medication_reminders': medicationReminders,
        'risk_alerts': riskAlerts,
        'chat_messages': chatMessages,
        'family_invitations': familyInvitations,
        'daily_summary': dailySummary,
        'marketing': marketing,
        'quiet_hours_start': '${quietHoursStart.hour}:${quietHoursStart.minute}',
        'quiet_hours_end': '${quietHoursEnd.hour}:${quietHoursEnd.minute}',
        'enable_quiet_hours': enableQuietHours,
      };

  factory NotificationSettings.fromJson(Map<String, dynamic> json) {
    return NotificationSettings()
      ..medicationReminders = json['medication_reminders'] ?? true
      ..riskAlerts = json['risk_alerts'] ?? true
      ..chatMessages = json['chat_messages'] ?? true
      ..familyInvitations = json['family_invitations'] ?? true
      ..dailySummary = json['daily_summary'] ?? true
      ..marketing = json['marketing'] ?? false
      ..enableQuietHours = json['enable_quiet_hours'] ?? false;
  }

  bool shouldNotify(String type) {
    switch (type) {
      case 'medication_reminder':
        return medicationReminders;
      case 'risk_alert':
        return riskAlerts;
      case 'chat_message':
        return chatMessages;
      case 'family_invitation':
        return familyInvitations;
      case 'daily_summary':
        return dailySummary;
      case 'marketing':
        return marketing;
      default:
        return true;
    }
  }

  bool isQuietHours() {
    if (!enableQuietHours) return false;
    final now = TimeOfDay.now();
    final start = quietHoursStart.hour * 60 + quietHoursStart.minute;
    final end = quietHoursEnd.hour * 60 + quietHoursEnd.minute;
    final current = now.hour * 60 + now.minute;
    if (start <= end) {
      return current >= start && current < end;
    } else {
      return current >= start || current < end;
    }
  }
}
```

## 6. 推送检查清单

- [ ] 本地通知权限请求
- [ ] 用药提醒定时准确
- [ ] 通知操作按钮可用
- [ ] FCM 集成正常
- [ ] 前台/后台/终止状态都能处理
- [ ] 通知渠道分类合理
- [ ] 用户偏好可配置
- [ ] 免打扰时段生效
- [ ] 深链接跳转正确
- [ ] 通知内容不泄露隐私
- [ ] 角标管理正确
- [ ] Token 注册和刷新

---

*及时、准确、不打扰的推送通知，让健康管理融入日常生活。*
