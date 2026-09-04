# APP后台任务与保活设计

> 本文档是家健镜系统 APP 后台任务与保活的完整设计说明，覆盖后台任务、进程保活、闹钟调度、WorkManager、电量优化。

## 1. 概述

### 1.1 设计目标

1. 后台任务可靠执行
2. 进程保活不被系统杀死
3. 低功耗，不影响续航
4. 兼容各厂商系统
5. 用户可配置

### 1.2 后台任务类型

| 类型 | 说明 | 触发方式 |
| --- | --- | --- |
| 定时任务 | 周期性执行 | AlarmManager / WorkManager |
| 即时任务 | 立即执行 | Service / JobScheduler |
| 延迟任务 | 延迟执行 | Handler / WorkManager |
| 前台任务 | 持续运行 | Foreground Service |

## 2. Android 后台任务

### 2.1 WorkManager

```kotlin
class MedicationReminderWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val medicineId = inputData.getString("medicine_id") ?: return Result.failure()
        val medicineName = inputData.getString("medicine_name") ?: "药品"

        // 发送提醒通知
        NotificationHelper.showMedicationReminder(
            context = applicationContext,
            medicineId = medicineId,
            medicineName = medicineName,
        )

        // 安排下一次提醒
        scheduleNextReminder(medicineId)

        return Result.success()
    }

    companion object {
        fun scheduleReminder(
            context: Context,
            medicineId: String,
            medicineName: String,
            triggerTime: Long,
        ) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.NOT_REQUIRED)
                .build()

            val workRequest = OneTimeWorkRequestBuilder<MedicationReminderWorker>()
                .setInputData(
                    workDataOf(
                        "medicine_id" to medicineId,
                        "medicine_name" to medicineName,
                    )
                )
                .setInitialDelay(triggerTime - System.currentTimeMillis(), TimeUnit.MILLISECONDS)
                .setConstraints(constraints)
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                "reminder_$medicineId",
                ExistingWorkPolicy.REPLACE,
                workRequest,
            )
        }
    }
}
```

### 2.2 AlarmManager

```kotlin
class AlarmScheduler {
    fun setExactAlarm(context: Context, triggerAtMillis: Long, pendingIntent: PendingIntent) {
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            alarmManager.setExactAndAllowWhileIdle(
                AlarmManager.RTC_WAKEUP,
                triggerAtMillis,
                pendingIntent,
            )
        } else {
            alarmManager.setExact(
                AlarmManager.RTC_WAKEUP,
                triggerAtMillis,
                pendingIntent,
            )
        }
    }

    fun setRepeatingAlarm(
        context: Context,
        triggerAtMillis: Long,
        intervalMillis: Long,
        pendingIntent: PendingIntent,
    ) {
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        alarmManager.setRepeating(
            AlarmManager.RTC_WAKEUP,
            triggerAtMillis,
            intervalMillis,
            pendingIntent,
        )
    }

    fun cancelAlarm(context: Context, pendingIntent: PendingIntent) {
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        alarmManager.cancel(pendingIntent)
    }
}
```

### 2.3 前台服务

```kotlin
class StepCounterService : Service() {
    private val NOTIFICATION_ID = 1001
    private val CHANNEL_ID = "step_counter_channel"

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 开始计步
        startStepCounting()
        return START_STICKY
    }

    private fun buildNotification(): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("家健镜")
            .setContentText("正在记录您的运动数据")
            .setSmallIcon(R.drawable.ic_footsteps)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "运动记录",
                NotificationManager.IMPORTANCE_LOW,
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
```

## 3. iOS 后台任务

### 3.1 Background Tasks

```swift
import BackgroundTasks

class BackgroundTaskManager {
    static let shared = BackgroundTaskManager()

    func register() {
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: "com.homecare.refresh",
            using: nil
        ) { task in
            self.handleAppRefresh(task: task as! BGAppRefreshTask)
        }

        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: "com.homecare.processing",
            using: nil
        ) { task in
            self.handleProcessing(task: task as! BGProcessingTask)
        }
    }

    func scheduleAppRefresh() {
        let request = BGAppRefreshTaskRequest(identifier: "com.homecare.refresh")
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)

        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            print("Could not schedule app refresh: \(error)")
        }
    }

    private func handleAppRefresh(task: BGAppRefreshTask) {
        scheduleAppRefresh()

        task.expirationHandler = {
            // 任务即将过期，清理
        }

        // 执行后台刷新
        refreshData { success in
            task.setTaskCompleted(success: success)
        }
    }

    private func handleProcessing(task: BGProcessingTask) {
        task.expirationHandler = {
            // 清理
        }

        // 执行耗时处理
        processHealthData { success in
            task.setTaskCompleted(success: success)
        }
    }
}
```

### 3.2 远程推送唤醒

```swift
func application(
    _ application: UIApplication,
    didReceiveRemoteNotification userInfo: [AnyHashable: Any],
    fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void
) {
    // 处理静默推送
    if let aps = userInfo["aps"] as? [String: Any], aps["content-available"] as? Int == 1 {
        // 后台数据更新
        updateData { result in
            completionHandler(result)
        }
    }
}
```

## 4. 进程保活

### 4.1 双进程守护

```kotlin
class DaemonService : Service() {
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 启动守护进程
        startDaemon()
        return START_STICKY
    }

    private fun startDaemon() {
        // 使用 JobScheduler 定期检查主进程
        val jobInfo = JobInfo.Builder(1001, ComponentName(this, DaemonJobService::class.java))
            .setPeriodic(15 * 60 * 1000) // 15分钟
            .setPersisted(true)
            .build()

        val scheduler = getSystemService(Context.JOB_SCHEDULER_SERVICE) as JobScheduler
        scheduler.schedule(jobInfo)
    }

    override fun onBind(intent: Intent?): IBinder? = null
}

class DaemonJobService : JobService() {
    override fun onStartJob(params: JobParameters?): Boolean {
        // 检查主进程是否存活
        if (!isMainProcessAlive()) {
            // 重启主进程
            val intent = packageManager.getLaunchIntentForPackage(packageName)
            startActivity(intent)
        }
        return false
    }

    override fun onStopJob(params: JobParameters?): Boolean = true

    private fun isMainProcessAlive(): Boolean {
        val am = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        return am.runningAppProcesses.any { it.processName == packageName }
    }
}
```

### 4.2 1像素 Activity

```kotlin
class OnePixelActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 设置1像素窗口
        val windowParams = window.attributes
        windowParams.gravity = Gravity.START or Gravity.TOP
        windowParams.x = 0
        windowParams.y = 0
        windowParams.height = 1
        windowParams.width = 1
        window.attributes = windowParams
    }

    override fun onDestroy() {
        super.onDestroy()
        // 重启主界面
    }
}
```

## 5. 电量优化

### 5.1 批量任务

```kotlin
class BatchTaskScheduler {
    fun scheduleBatchTasks(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiresCharging(true)  // 充电时执行
            .setRequiredNetworkType(NetworkType.UNMETERED)  // WiFi 下执行
            .setRequiresBatteryNotLow(true)  // 电量充足时
            .build()

        val workRequest = PeriodicWorkRequestBuilder<BatchSyncWorker>(
            1, TimeUnit.HOURS
        )
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            "batch_sync",
            ExistingPeriodicWorkPolicy.KEEP,
            workRequest,
        )
    }
}
```

### 5.2 省电模式检测

```kotlin
class PowerSavingManager {
    fun isPowerSavingMode(context: Context): Boolean {
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        return powerManager.isPowerSaveMode
    }

    fun shouldReduceFunctionality(context: Context): Boolean {
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        val batteryLevel = getBatteryLevel(context)

        return powerManager.isPowerSaveMode || batteryLevel < 20
    }

    private fun getBatteryLevel(context: Context): Int {
        val batteryIntent = ContextCompat.registerReceiver(
            context,
            null,
            IntentFilter(Intent.ACTION_BATTERY_CHANGED),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        val level = batteryIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        return if (level != -1 && scale != -1) (level * 100 / scale) else 100
    }
}
```

## 6. 厂商适配

### 6.1 自启动权限

```kotlin
class AutoStartPermissionHelper {
    fun requestAutoStartPermission(context: Context) {
        val manufacturer = Build.MANUFACTURER.lowercase()

        when {
            manufacturer.contains("xiaomi") -> openXiaomiAutoStart(context)
            manufacturer.contains("huawei") -> openHuaweiAutoStart(context)
            manufacturer.contains("oppo") -> openOppoAutoStart(context)
            manufacturer.contains("vivo") -> openVivoAutoStart(context)
            manufacturer.contains("meizu") -> openMeizuAutoStart(context)
            else -> {
                // 通用设置
                val intent = Intent(Settings.ACTION_SETTINGS)
                context.startActivity(intent)
            }
        }
    }

    private fun openXiaomiAutoStart(context: Context) {
        try {
            val intent = Intent()
            intent.component = ComponentName(
                "com.miui.securitycenter",
                "com.miui.permcenter.autostart.AutoStartManagementActivity",
            )
            context.startActivity(intent)
        } catch (e: Exception) {
            context.startActivity(Intent(Settings.ACTION_SETTINGS))
        }
    }
}
```

## 7. 后台任务检查清单

- [ ] WorkManager
- [ ] AlarmManager
- [ ] 前台服务
- [ ] iOS Background Tasks
- [ ] 远程推送唤醒
- [ ] 双进程守护
- [ ] 1像素保活
- [ ] 批量任务
- [ ] 省电模式
- [ ] 厂商适配
- [ ] 自启动权限
- [ ] 电量优化

---

*可靠的后台任务是健康提醒的保障。智能保活、低功耗运行，让提醒永不缺席。*
