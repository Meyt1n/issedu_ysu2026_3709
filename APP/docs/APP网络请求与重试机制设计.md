# APP网络请求与重试机制设计

> 本文档是家健镜系统 APP 网络请求与重试机制的完整设计说明，覆盖请求封装、重试策略、超时控制、缓存策略、错误处理。

## 1. 概述

### 1.1 设计目标

1. 请求成功率 > 99%
2. 平均响应时间 < 500ms
3. 弱网环境可用
4. 自动重试
5. 请求可取消

### 1.2 网络层架构

| 层级 | 职责 |
| --- | --- |
| API 层 | 接口定义、参数封装 |
| 拦截器层 | 鉴权、日志、重试 |
| HTTP 层 | 实际网络请求 |
| 缓存层 | 响应缓存 |

## 2. 请求封装

### 2.1 API 客户端

```dart
class ApiClient {
  final Dio _dio;
  final String baseUrl;

  ApiClient({required this.baseUrl})
      : _dio = Dio(BaseOptions(
          baseUrl: baseUrl,
          connectTimeout: Duration(seconds: 10),
          receiveTimeout: Duration(seconds: 15),
          sendTimeout: Duration(seconds: 10),
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
        )) {
    _setupInterceptors();
  }

  void _setupInterceptors() {
    _dio.interceptors.addAll([
      AuthInterceptor(),
      RetryInterceptor(),
      LoggingInterceptor(),
      ErrorInterceptor(),
    ]);
  }

  Future<Response<T>> get<T>(
    String path, {
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) {
    return _dio.get<T>(path, queryParameters: queryParameters, options: options);
  }

  Future<Response<T>> post<T>(
    String path, {
    dynamic data,
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) {
    return _dio.post<T>(path, data: data, queryParameters: queryParameters, options: options);
  }

  Future<Response<T>> put<T>(
    String path, {
    dynamic data,
    Options? options,
  }) {
    return _dio.put<T>(path, data: data, options: options);
  }

  Future<Response<T>> delete<T>(
    String path, {
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) {
    return _dio.delete<T>(path, queryParameters: queryParameters, options: options);
  }
}
```

### 2.2 鉴权拦截器

```dart
class AuthInterceptor extends Interceptor {
  final TokenManager _tokenManager = TokenManager.instance;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final token = _tokenManager.accessToken;
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    super.onRequest(options, handler);
  }

  @override
  void onError(DioError err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode == 401) {
      // Token 过期，尝试刷新
      try {
        final newToken = await _tokenManager.refreshToken();
        if (newToken != null) {
          // 重试原请求
          final options = err.requestOptions;
          options.headers['Authorization'] = 'Bearer $newToken';
          final response = await Dio().fetch(options);
          return handler.resolve(response);
        }
      } catch (e) {
        // 刷新失败，跳登录
        _navigateToLogin();
      }
    }
    super.onError(err, handler);
  }
}
```

## 3. 重试机制

### 3.1 重试拦截器

```dart
class RetryInterceptor extends Interceptor {
  final int maxRetries;
  final Duration retryDelay;

  RetryInterceptor({this.maxRetries = 3, this.retryDelay = const Duration(seconds: 1)});

  @override
  void onError(DioError err, ErrorInterceptorHandler handler) async {
    if (_shouldRetry(err)) {
      for (int i = 0; i < maxRetries; i++) {
        await Future.delayed(retryDelay * (i + 1)); // 指数退避

        try {
          final response = await Dio().fetch(err.requestOptions);
          return handler.resolve(response);
        } on DioError catch (e) {
          if (!_shouldRetry(e)) {
            return handler.next(e);
          }
        }
      }
    }
    super.onError(err, handler);
  }

  bool _shouldRetry(DioError err) {
    // 网络错误重试
    if (err.type == DioErrorType.connectionTimeout ||
        err.type == DioErrorType.receiveTimeout ||
        err.type == DioErrorType.sendTimeout ||
        err.type == DioErrorType.connectionError) {
      return true;
    }

    // 5xx 错误重试
    if (err.response?.statusCode != null &&
        err.response!.statusCode! >= 500 &&
        err.response!.statusCode! < 600) {
      return true;
    }

    // 429 限流重试
    if (err.response?.statusCode == 429) {
      return true;
    }

    return false;
  }
}
```

### 3.2 指数退避

```dart
class ExponentialBackoff {
  final Duration initialDelay;
  final Duration maxDelay;
  final double multiplier;

  ExponentialBackoff({
    this.initialDelay = const Duration(milliseconds: 100),
    this.maxDelay = const Duration(seconds: 30),
    this.multiplier = 2.0,
  });

  Duration delay(int attempt) {
    final delay = initialDelay.inMilliseconds * (multiplier * attempt);
    final jitter = Random().nextInt(100); // 随机抖动
    return Duration(
      milliseconds: min(delay.toInt() + jitter, maxDelay.inMilliseconds),
    );
  }
}
```

### 3.3 断路器

```dart
class CircuitBreaker {
  final int failureThreshold;
  final Duration recoveryTimeout;
  int _failureCount = 0;
  CircuitState _state = CircuitState.closed;
  DateTime? _lastFailureTime;

  CircuitBreaker({this.failureThreshold = 5, this.recoveryTimeout = const Duration(seconds: 30)});

  bool allowRequest() {
    if (_state == CircuitState.open) {
      if (_lastFailureTime != null &&
          DateTime.now().difference(_lastFailureTime!) > recoveryTimeout) {
        _state = CircuitState.halfOpen;
        return true;
      }
      return false;
    }
    return true;
  }

  void recordSuccess() {
    _failureCount = 0;
    _state = CircuitState.closed;
  }

  void recordFailure() {
    _failureCount++;
    _lastFailureTime = DateTime.now();

    if (_failureCount >= failureThreshold) {
      _state = CircuitState.open;
    }
  }
}

enum CircuitState { closed, open, halfOpen }
```

## 4. 超时控制

### 4.1 超时配置

```dart
class TimeoutConfig {
  final Duration connectTimeout;
  final Duration receiveTimeout;
  final Duration sendTimeout;
  final Duration totalTimeout;

  const TimeoutConfig({
    this.connectTimeout = const Duration(seconds: 10),
    this.receiveTimeout = const Duration(seconds: 15),
    this.sendTimeout = const Duration(seconds: 10),
    this.totalTimeout = const Duration(seconds: 30),
  });

  static const TimeoutConfig standard = TimeoutConfig();
  static const TimeoutConfig fast = TimeoutConfig(
    connectTimeout: Duration(seconds: 5),
    receiveTimeout: Duration(seconds: 8),
    totalTimeout: Duration(seconds: 15),
  );
  static const TimeoutConfig slow = TimeoutConfig(
    connectTimeout: Duration(seconds: 30),
    receiveTimeout: Duration(seconds: 60),
    totalTimeout: Duration(seconds: 90),
  );
}
```

### 4.2 请求取消

```dart
class CancelableRequest<T> {
  final CancelToken _cancelToken = CancelToken();
  final Future<T> Function(CancelToken) _request;
  Future<T>? _future;

  CancelableRequest(this._request);

  Future<T> execute() {
    _future = _request(_cancelToken);
    return _future!;
  }

  void cancel() {
    _cancelToken.cancel('用户取消');
  }

  bool get isCancelled => _cancelToken.isCancelled;
}

// 使用
class SearchBloc {
  CancelableRequest? _currentRequest;

  void search(String keyword) {
    _currentRequest?.cancel();
    _currentRequest = CancelableRequest((token) => api.search(keyword, cancelToken: token));
    _currentRequest!.execute();
  }

  void dispose() {
    _currentRequest?.cancel();
  }
}
```

## 5. 缓存策略

### 5.1 响应缓存

```dart
class ResponseCache {
  final Map<String, CacheEntry> _cache = {};
  final int maxSize;
  final Duration defaultTtl;

  ResponseCache({this.maxSize = 100, this.defaultTtl = const Duration(minutes: 5)});

  Future<T?> get<T>(String key) async {
    final entry = _cache[key];
    if (entry == null || entry.isExpired) {
      _cache.remove(key);
      return null;
    }
    return entry.value as T;
  }

  void set<T>(String key, T value, {Duration? ttl}) {
    if (_cache.length >= maxSize) {
      _evictOldest();
    }
    _cache[key] = CacheEntry(value: value, ttl: ttl ?? defaultTtl);
  }

  void _evictOldest() {
    final oldestKey = _cache.entries
        .reduce((a, b) => a.value.createdAt.isBefore(b.value.createdAt) ? a : b)
        .key;
    _cache.remove(oldestKey);
  }

  void invalidate(String key) {
    _cache.remove(key);
  }

  void clear() {
    _cache.clear();
  }
}

class CacheEntry {
  final dynamic value;
  final DateTime createdAt;
  final Duration ttl;

  CacheEntry({required this.value, required this.ttl})
      : createdAt = DateTime.now();

  bool get isExpired => DateTime.now().difference(createdAt) > ttl;
}
```

### 5.2 缓存策略

```dart
enum CacheStrategy {
  networkOnly,      // 只用网络
  cacheOnly,        // 只用缓存
  cacheFirst,       // 先缓存，缓存没有再网络
  networkFirst,     // 先网络，失败用缓存
  staleWhileRevalidate, // 先用缓存，同时网络更新
}

class CachedApiClient {
  final ApiClient _api;
  final ResponseCache _cache;

  Future<T> request<T>(
    String key,
    Future<T> Function() networkRequest, {
    CacheStrategy strategy = CacheStrategy.networkFirst,
    Duration? ttl,
  }) async {
    switch (strategy) {
      case CacheStrategy.networkOnly:
        return networkRequest();

      case CacheStrategy.cacheOnly:
        return _cache.get<T>(key) ?? (throw CacheMissException());

      case CacheStrategy.cacheFirst:
        final cached = await _cache.get<T>(key);
        if (cached != null) return cached;
        final result = await networkRequest();
        _cache.set(key, result, ttl: ttl);
        return result;

      case CacheStrategy.networkFirst:
        try {
          final result = await networkRequest();
          _cache.set(key, result, ttl: ttl);
          return result;
        } catch (e) {
          final cached = await _cache.get<T>(key);
          if (cached != null) return cached;
          rethrow;
        }

      case CacheStrategy.staleWhileRevalidate:
        final cached = await _cache.get<T>(key);
        // 异步更新缓存
        networkRequest().then((result) => _cache.set(key, result, ttl: ttl));
        if (cached != null) return cached;
        return networkRequest();
    }
  }
}
```

## 6. 错误处理

### 6.1 错误分类

```dart
class ApiException implements Exception {
  final String message;
  final int? statusCode;
  final ApiErrorType type;
  final dynamic data;

  ApiException({
    required this.message,
    this.statusCode,
    required this.type,
    this.data,
  });

  factory ApiException.fromDioError(DioError error) {
    switch (error.type) {
      case DioErrorType.connectionTimeout:
      case DioErrorType.sendTimeout:
      case DioErrorType.receiveTimeout:
        return ApiException(
          message: '网络连接超时，请检查网络设置',
          type: ApiErrorType.timeout,
        );
      case DioErrorType.connectionError:
        return ApiException(
          message: '网络连接失败，请检查网络设置',
          type: ApiErrorType.network,
        );
      case DioErrorType.badResponse:
        return _handleHttpError(error.response!);
      default:
        return ApiException(
          message: '未知错误',
          type: ApiErrorType.unknown,
        );
    }
  }

  static ApiException _handleHttpError(Response response) {
    switch (response.statusCode) {
      case 400:
        return ApiException(message: '请求参数错误', statusCode: 400, type: ApiErrorType.badRequest);
      case 401:
        return ApiException(message: '未授权，请重新登录', statusCode: 401, type: ApiErrorType.unauthorized);
      case 403:
        return ApiException(message: '没有权限', statusCode: 403, type: ApiErrorType.forbidden);
      case 404:
        return ApiException(message: '资源不存在', statusCode: 404, type: ApiErrorType.notFound);
      case 429:
        return ApiException(message: '请求过于频繁，请稍后再试', statusCode: 429, type: ApiErrorType.rateLimit);
      case 500:
        return ApiException(message: '服务器错误', statusCode: 500, type: ApiErrorType.serverError);
      default:
        return ApiException(message: '请求失败', statusCode: response.statusCode, type: ApiErrorType.httpError);
    }
  }
}

enum ApiErrorType {
  network,
  timeout,
  badRequest,
  unauthorized,
  forbidden,
  notFound,
  rateLimit,
  serverError,
  httpError,
  unknown,
}
```

## 7. 网络状态监听

### 7.1 连接状态

```dart
class NetworkMonitor {
  final Connectivity _connectivity = Connectivity();
  final StreamController<ConnectivityResult> _controller = StreamController.broadcast();

  Stream<ConnectivityResult> get onConnectivityChanged => _controller.stream;

  void init() {
    _connectivity.onConnectivityChanged.listen((result) {
      _controller.add(result);
    });
  }

  Future<ConnectivityResult> get currentStatus => _connectivity.checkConnectivity();

  Future<bool> get isConnected async {
    final result = await currentStatus;
    return result != ConnectivityResult.none;
  }
}
```

### 7.2 离线队列

```dart
class OfflineQueue {
  final List<QueuedRequest> _queue = [];
  final NetworkMonitor _monitor;

  OfflineQueue(this._monitor) {
    _monitor.onConnectivityChanged.listen((result) {
      if (result != ConnectivityResult.none) {
        _flushQueue();
      }
    });
  }

  void enqueue(QueuedRequest request) {
    _queue.add(request);
    _persistQueue();
  }

  Future<void> _flushQueue() async {
    while (_queue.isNotEmpty) {
      final request = _queue.first;
      try {
        await request.execute();
        _queue.removeAt(0);
      } catch (e) {
        // 失败等待下次网络恢复
        break;
      }
    }
    _persistQueue();
  }
}
```

## 8. 网络请求检查清单

- [ ] API 客户端封装
- [ ] 鉴权拦截器
- [ ] 重试机制
- [ ] 指数退避
- [ ] 断路器
- [ ] 超时控制
- [ ] 请求取消
- [ ] 响应缓存
- [ ] 缓存策略
- [ ] 错误处理
- [ ] 网络状态监听
- [ ] 离线队列

---

*稳定的网络层是 APP 体验的基石。智能重试、优雅降级，让网络波动不再影响用户体验。*
