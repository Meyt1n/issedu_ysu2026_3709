# APP错误处理与异常恢复设计

> 本文档是家健镜系统 APP 错误处理与异常恢复的完整设计说明，覆盖异常分类、错误传播、用户提示、自动恢复、崩溃监控。

## 1. 概述

### 1.1 设计目标

1. 不崩溃：异常不导致应用退出
2. 可感知：用户知道发生了什么
3. 可恢复：提供重试或降级方案
4. 可追踪：错误可上报和分析
5. 可预防：常见错误有防护机制

### 1.2 异常分类

| 类型 | 说明 | 示例 |
| --- | --- | --- |
| 网络异常 | 网络请求失败 | 超时、断网、500 |
| 业务异常 | 业务逻辑错误 | 药品不存在、权限不足 |
| 数据异常 | 数据格式错误 | JSON 解析失败、空值 |
| 平台异常 | 平台通道错误 | 蓝牙断开、传感器不可用 |
| 未知异常 | 未预料的错误 | 空指针、类型转换 |

## 2. 异常体系

### 2.1 Failure 基类

```dart
abstract class Failure {
  final String message;
  final StackTrace? stackTrace;

  Failure(this.message, [this.stackTrace]);

  @override
  String toString() => '$runtimeType: $message';
}

class ServerFailure extends Failure {
  final int statusCode;
  ServerFailure(String message, this.statusCode) : super(message);
}

class NetworkFailure extends Failure {
  NetworkFailure() : super('网络连接失败，请检查网络设置');
}

class CacheFailure extends Failure {
  CacheFailure() : super('本地数据读取失败');
}

class ValidationFailure extends Failure {
  final String field;
  ValidationFailure(this.field, String message) : super(message);
}

class UnknownFailure extends Failure {
  UnknownFailure(String message, StackTrace stackTrace)
      : super(message, stackTrace);
}
```

### 2.2 Either 错误处理

```dart
// 用 Either 包装可能失败的操作
abstract class Either<L, R> {
  const Either();

  B fold<B>(B Function(L l) ifLeft, B Function(R r) ifRight);

  bool get isLeft => fold((_) => true, (_) => false);
  bool get isRight => fold((_) => false, (_) => true);
}

class Left<L, R> extends Either<L, R> {
  final L value;
  const Left(this.value);

  @override
  B fold<B>(B Function(L l) ifLeft, B Function(R r) ifRight) => ifLeft(value);
}

class Right<L, R> extends Either<L, R> {
  final R value;
  const Right(this.value);

  @override
  B fold<B>(B Function(L l) ifLeft, B Function(R r) ifRight) => ifRight(value);
}
```

### 2.3 异常转换

```dart
class ExceptionHandler {
  static Failure handleException(Exception e, [StackTrace? stackTrace]) {
    if (e is SocketException) {
      return NetworkFailure();
    } else if (e is TimeoutException) {
      return ServerFailure('请求超时，请稍后重试', 408);
    } else if (e is HttpException) {
      return ServerFailure(e.message, 500);
    } else if (e is FormatException) {
      return UnknownFailure('数据格式错误: ${e.message}', stackTrace ?? StackTrace.current);
    } else if (e is PlatformException) {
      return _handlePlatformException(e);
    } else {
      return UnknownFailure(e.toString(), stackTrace ?? StackTrace.current);
    }
  }

  static Failure _handlePlatformException(PlatformException e) {
    switch (e.code) {
      case 'PERMISSION_DENIED':
        return ValidationFailure('permission', '权限被拒绝');
      case 'BLUETOOTH_DISABLED':
        return NetworkFailure();
      default:
        return UnknownFailure(e.message ?? '未知平台错误', StackTrace.current);
    }
  }
}
```

## 3. Repository 层错误处理

### 3.1 try-catch 包装

```dart
@override
Future<Either<Failure, List<Medicine>>> getMedicines(String memberId) async {
  try {
    if (!await _networkInfo.isConnected) {
      return Left(NetworkFailure());
    }

    final remoteMedicines = await _remote.getMedicines(memberId);
    await _local.cacheMedicines(remoteMedicines);
    return Right(remoteMedicines.map((e) => e.toEntity()).toList());
  } on ServerException catch (e) {
    return Left(ServerFailure(e.message, e.statusCode));
  } on SocketException {
    return Left(NetworkFailure());
  } on TimeoutException {
    return Left(ServerFailure('请求超时', 408));
  } catch (e, stackTrace) {
    _errorReporter.report(e, stackTrace);
    return Left(UnknownFailure(e.toString(), stackTrace));
  }
}
```

## 4. ViewModel 层错误处理

### 4.1 错误状态管理

```dart
class MedicineViewModel extends ChangeNotifier {
  final GetMedicinesUseCase _getMedicines;
  MedicineViewModel(this._getMedicines);

  List<Medicine> _medicines = [];
  List<Medicine> get medicines => _medicines;

  bool _isLoading = false;
  bool get isLoading => _isLoading;

  Failure? _error;
  Failure? get error => _error;
  bool get hasError => _error != null;

  Future<void> loadMedicines(String memberId) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    final result = await _getMedicines(memberId);
    result.fold(
      (failure) {
        _error = failure;
        _errorReporter.reportFailure(failure);
      },
      (medicines) => _medicines = medicines,
    );

    _isLoading = false;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
```

## 5. UI 层错误展示

### 5.1 错误提示组件

```dart
class ErrorView extends StatelessWidget {
  final Failure error;
  final VoidCallback? onRetry;

  ErrorView({required this.error, this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.error_outline, size: 64, color: Colors.grey),
          SizedBox(height: 16),
          Text(
            error.message,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 16, color: Colors.grey[700]),
          ),
          SizedBox(height: 24),
          if (onRetry != null)
            ElevatedButton.icon(
              onPressed: onRetry,
              icon: Icon(Icons.refresh),
              label: Text('重试'),
            ),
        ],
      ),
    );
  }
}

// 使用
class MedicinePage extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<MedicineViewModel>(
      builder: (context, viewModel, child) {
        if (viewModel.isLoading) {
          return Center(child: CircularProgressIndicator());
        }
        if (viewModel.hasError) {
          return ErrorView(
            error: viewModel.error!,
            onRetry: () => viewModel.loadMedicines('memberId'),
          );
        }
        return MedicineList(medicines: viewModel.medicines);
      },
    );
  }
}
```

### 5.2 SnackBar 提示

```dart
void showErrorSnackBar(BuildContext context, Failure error) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(error.message),
      backgroundColor: Colors.red,
      action: SnackBarAction(
        label: '重试',
        textColor: Colors.white,
        onPressed: () {
          // 重试逻辑
        },
      ),
      duration: Duration(seconds: 5),
    ),
  );
}
```

## 6. 全局异常捕获

### 6.1 FlutterError 与 runZonedGuarded

```dart
void main() {
  runZonedGuarded(() {
    WidgetsFlutterBinding.ensureInitialized();

    // 捕获 Flutter 框架异常
    FlutterError.onError = (FlutterErrorDetails details) {
      ErrorReporter.instance.reportFlutterError(details);
    };

    runApp(MyApp());
  }, (error, stackTrace) {
    // 捕获未处理的异步异常
    ErrorReporter.instance.reportError(error, stackTrace);
  });
}
```

### 6.2 错误上报

```dart
class ErrorReporter {
  static final ErrorReporter instance = ErrorReporter._();
  ErrorReporter._();

  final List<ErrorLog> _logs = [];

  void reportError(dynamic error, StackTrace stackTrace) {
    final log = ErrorLog(
      timestamp: DateTime.now(),
      error: error.toString(),
      stackTrace: stackTrace.toString(),
    );
    _logs.add(log);
    _uploadToServer(log);
  }

  void reportFlutterError(FlutterErrorDetails details) {
    reportError(details.exception, details.stack ?? StackTrace.current);
  }

  void reportFailure(Failure failure) {
    if (failure is UnknownFailure) {
      reportError(failure.message, failure.stackTrace ?? StackTrace.current);
    }
  }

  Future<void> _uploadToServer(ErrorLog log) async {
    try {
      // 上报到服务器
    } catch (_) {
      // 上报失败，本地缓存
    }
  }
}
```

## 7. 自动恢复策略

### 7.1 重试机制

```dart
class RetryHelper {
  static Future<T> withRetry<T>(
    Future<T> Function() action, {
    int maxRetries = 3,
    Duration delay = const Duration(seconds: 1),
  }) async {
    int attempts = 0;
    while (true) {
      try {
        return await action();
      } catch (e) {
        attempts++;
        if (attempts >= maxRetries) rethrow;
        await Future.delayed(delay * attempts);
      }
    }
  }
}

// 使用
final result = await RetryHelper.withRetry(
  () => _api.getMedicines(),
  maxRetries: 3,
  delay: Duration(seconds: 1),
);
```

### 7.2 降级策略

```dart
class FallbackStrategy {
  Future<Either<Failure, List<Medicine>>> getMedicines(
    MedicineRemoteDataSource remote,
    MedicineLocalDataSource local,
  ) async {
    try {
      // 优先远程
      final data = await remote.getMedicines();
      return Right(data);
    } catch (_) {
      // 降级到本地缓存
      try {
        final cached = await local.getCachedMedicines();
        return Right(cached);
      } catch (e) {
        return Left(CacheFailure());
      }
    }
  }
}
```

## 8. 错误处理检查清单

- [ ] 异常分类
- [ ] Failure 基类
- [ ] Either 错误处理
- [ ] 异常转换
- [ ] Repository 层
- [ ] ViewModel 层
- [ ] UI 层展示
- [ ] 全局异常捕获
- [ ] 错误上报
- [ ] 重试机制
- [ ] 降级策略
- [ ] 崩溃监控

---

*健壮的错误处理是 APP 稳定性的保障。不崩溃、可恢复、可追踪，让用户体验流畅。*
