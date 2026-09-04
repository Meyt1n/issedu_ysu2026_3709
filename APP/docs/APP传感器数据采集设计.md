# APP传感器数据采集设计

> 本文档是家健镜系统 APP 传感器数据采集的完整设计说明，覆盖传感器类型、数据采集、数据处理、功耗优化、数据上传。

## 1. 概述

### 1.1 设计目标

1. 数据准确：传感器数据精度达标
2. 低功耗：后台采集耗电 < 5%/小时
3. 实时性：数据延迟 < 1 秒
4. 连续性：支持长时间持续采集
5. 兼容性：支持多种设备和传感器

### 1.2 传感器类型

| 传感器 | 数据 | 用途 |
| --- | --- | --- |
| 加速度计 | x/y/z 加速度 | 运动检测、步数 |
| 陀螺仪 | 角速度 | 姿态识别 |
| 心率传感器 | BPM | 健康监测 |
| 血氧传感器 | SpO2 | 健康监测 |
| 体温传感器 | 温度 | 健康监测 |
| GPS | 位置 | 运动轨迹 |
| 气压计 | 气压 | 海拔、楼层 |

## 2. 传感器采集

### 2.1 加速度计采集

```dart
class AccelerometerCollector {
  final StreamController<AccelerometerEvent> _controller = StreamController.broadcast();
  StreamSubscription? _subscription;
  int _sampleRate = 50; // Hz

  Stream<AccelerometerEvent> get stream => _controller.stream;

  void start() {
    _subscription = accelerometerEvents.listen((event) {
      _controller.add(event);
    });
  }

  void stop() {
    _subscription?.cancel();
  }

  void setSampleRate(int rate) {
    _sampleRate = rate;
    // 平台特定设置
  }
}
```

### 2.2 心率采集

```dart
class HeartRateCollector {
  final StreamController<int> _controller = StreamController.broadcast();
  StreamSubscription? _subscription;

  Stream<int> get stream => _controller.stream;

  Future<void> start() async {
    // 检查权限
    final permission = await Permission.sensors.request();
    if (!permission.isGranted) {
      throw PermissionDeniedException();
    }

    // 开始采集
    _subscription = heartRateEvents.listen((bpm) {
      _controller.add(bpm);
    });
  }

  void stop() {
    _subscription?.cancel();
  }
}
```

### 2.3 GPS 采集

```dart
class LocationCollector {
  final StreamController<Position> _controller = StreamController.broadcast();
  StreamSubscription? _subscription;

  Stream<Position> get stream => _controller.stream;

  Future<void> start() async {
    // 检查权限
    final permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      await Geolocator.requestPermission();
    }

    // 开始定位
    _subscription = Geolocator.getPositionStream(
      locationSettings: LocationSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 10, // 10米更新一次
      ),
    ).listen((position) {
      _controller.add(position);
    });
  }

  void stop() {
    _subscription?.cancel();
  }
}
```

## 3. 数据处理

### 3.1 数据滤波

```dart
class LowPassFilter {
  final double alpha;
  double? _lastValue;

  LowPassFilter({this.alpha = 0.1});

  double filter(double value) {
    if (_lastValue == null) {
      _lastValue = value;
      return value;
    }
    _lastValue = _lastValue! + alpha * (value - _lastValue!);
    return _lastValue!;
  }
}

class KalmanFilter {
  double _estimate = 0;
  double _errorCovariance = 1;
  final double _processNoise = 0.01;
  final double _measurementNoise = 0.1;

  double filter(double measurement) {
    // 预测
    _errorCovariance += _processNoise;

    // 更新
    final kalmanGain = _errorCovariance / (_errorCovariance + _measurementNoise);
    _estimate += kalmanGain * (measurement - _estimate);
    _errorCovariance = (1 - kalmanGain) * _errorCovariance;

    return _estimate;
  }
}
```

### 3.2 步数计算

```dart
class StepCounter {
  final LowPassFilter _filter = LowPassFilter(alpha: 0.2);
  int _steps = 0;
  double _lastMagnitude = 0;
  bool _inStep = false;
  final double _threshold = 10.5; // m/s^2

  int process(AccelerometerEvent event) {
    // 计算合加速度
    final magnitude = sqrt(
      event.x * event.x + event.y * event.y + event.z * event.z,
    );

    // 滤波
    final filtered = _filter.filter(magnitude);

    // 峰值检测
    if (filtered > _threshold && !_inStep) {
      if (_lastMagnitude < _threshold) {
        _steps++;
        _inStep = true;
      }
    } else if (filtered < _threshold) {
      _inStep = false;
    }

    _lastMagnitude = filtered;
    return _steps;
  }

  void reset() {
    _steps = 0;
  }
}
```

### 3.3 活动识别

```dart
class ActivityRecognizer {
  String recognize(List<AccelerometerEvent> window) {
    // 计算统计特征
    final magnitudes = window.map((e) =>
      sqrt(e.x * e.x + e.y * e.y + e.z * e.z)
    ).toList();

    final mean = magnitudes.reduce((a, b) => a + b) / magnitudes.length;
    final variance = magnitudes.map((m) => (m - mean) * (m - mean))
        .reduce((a, b) => a + b) / magnitudes.length;
    final std = sqrt(variance);

    // 简单分类
    if (std < 0.1) {
      return "静止";
    } else if (std < 1.0) {
      return "步行";
    } else if (std < 3.0) {
      return "跑步";
    } else {
      return "剧烈运动";
    }
  }
}
```

## 4. 功耗优化

### 4.1 采样率动态调整

```dart
class AdaptiveSampling {
  int _currentRate = 50; // Hz
  String _activity = "静止";

  int get sampleRate => _currentRate;

  void updateActivity(String activity) {
    _activity = activity;

    switch (activity) {
      case "静止":
        _currentRate = 10; // 低采样率
        break;
      case "步行":
        _currentRate = 50; // 中等采样率
        break;
      case "跑步":
        _currentRate = 100; // 高采样率
        break;
      default:
        _currentRate = 50;
    }
  }
}
```

### 4.2 批量上传

```dart
class BatchUploader {
  final List<SensorData> _buffer = [];
  final int _batchSize = 100;
  final Duration _maxInterval = Duration(minutes: 5);
  Timer? _timer;

  void add(SensorData data) {
    _buffer.add(data);

    if (_buffer.length >= _batchSize) {
      _upload();
    }
  }

  void start() {
    _timer = Timer.periodic(_maxInterval, (_) {
      if (_buffer.isNotEmpty) {
        _upload();
      }
    });
  }

  Future<void> _upload() async {
    if (_buffer.isEmpty) return;

    final batch = List.from(_buffer);
    _buffer.clear();

    try {
      await api.uploadSensorData(batch);
    } catch (e) {
      // 上传失败，放回缓冲区
      _buffer.insertAll(0, batch);
    }
  }

  void stop() {
    _timer?.cancel();
    if (_buffer.isNotEmpty) {
      _upload();
    }
  }
}
```

### 4.3 后台采集

```dart
class BackgroundCollector {
  Future<void> startBackgroundCollection() async {
    // Android: 前台服务
    // iOS: 后台模式

    // 注册后台任务
    await BackgroundFetch.configure(
      BackgroundFetchConfig(
        minimumFetchInterval: 15,
        stopOnTerminate: false,
        enableHeadless: true,
      ),
      _onBackgroundFetch,
    );
  }

  void _onBackgroundFetch(String taskId) async {
    // 采集传感器数据
    final data = await _collectSensorData();

    // 上传
    await _uploadData(data);

    BackgroundFetch.finish(taskId);
  }
}
```

## 5. 数据存储

### 5.1 本地存储

```dart
class SensorDataDao {
  final Database _db;

  Future<void> insert(SensorData data) async {
    await _db.insert(
      'sensor_data',
      data.toMap(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> insertBatch(List<SensorData> batch) async {
    final batch_ = _db.batch();
    for (final data in batch) {
      batch_.insert('sensor_data', data.toMap());
    }
    await batch_.commit(noResult: true);
  }

  Future<List<SensorData>> getUnsynced() async {
    final maps = await _db.query(
      'sensor_data',
      where: 'synced = ?',
      whereArgs: [0],
      limit: 1000,
    );
    return maps.map((m) => SensorData.fromMap(m)).toList();
  }

  Future<void> markSynced(List<String> ids) async {
    final batch = _db.batch();
    for (final id in ids) {
      batch.update(
        'sensor_data',
        {'synced': 1},
        where: 'id = ?',
        whereArgs: [id],
      );
    }
    await batch.commit(noResult: true);
  }
}
```

## 6. 数据上传

### 6.1 上传策略

```dart
class UploadStrategy {
  Future<void> upload(List<SensorData> data) async {
    // 1. 检查网络
    final connectivity = await Connectivity().checkConnectivity();
    if (connectivity == ConnectivityResult.none) {
      return; // 无网络，等待
    }

    // 2. WiFi 下全量上传，移动网络下只上传关键数据
    if (connectivity == ConnectivityResult.wifi) {
      await _uploadAll(data);
    } else {
      await _uploadCritical(data);
    }
  }

  Future<void> _uploadAll(List<SensorData> data) async {
    await api.uploadSensorData(data);
  }

  Future<void> _uploadCritical(List<SensorData> data) async {
    // 只上传异常数据
    final critical = data.where((d) => d.isAnomaly).toList();
    if (critical.isNotEmpty) {
      await api.uploadSensorData(critical);
    }
  }
}
```

## 7. 传感器采集检查清单

- [ ] 加速度计
- [ ] 陀螺仪
- [ ] 心率传感器
- [ ] 血氧传感器
- [ ] GPS
- [ ] 数据滤波
- [ ] 步数计算
- [ ] 活动识别
- [ ] 采样率调整
- [ ] 批量上传
- [ ] 后台采集
- [ ] 本地存储

---

*传感器是健康数据的源头。精准采集、智能处理、低功耗运行，让健康数据源源不断。*
