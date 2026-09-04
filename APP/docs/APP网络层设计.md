# APP网络层设计

> 本文档是家健镜 APP 网络层的完整设计说明，覆盖 Dio 配置、拦截器、Token 刷新、错误处理、缓存、超时重试。面向移动端开发者，作为网络层实现的权威依据。

## 1. 网络层概述

### 1.1 设计目标

1. **统一配置**：BaseURL、超时、Header 统一管理
2. **自动认证**：Token 自动附加和刷新
3. **错误统一**：所有错误统一处理和转换
4. **缓存策略**：支持离线缓存和请求缓存
5. **可观测**：请求日志、性能监控
6. **可扩展**：易于添加新的拦截器和转换器

### 1.2 技术选型

- **HTTP 客户端**：Dio
- **序列化**：json_serializable
- **缓存**：dio_cache_interceptor + Hive
- **日志**：dio interceptor + logger

## 2. Dio 配置

### 2.1 基础配置

```dart
class ApiClient {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://api.homecare.example.com',
  );

  static const Duration connectTimeout = Duration(seconds: 10);
  static const Duration receiveTimeout = Duration(seconds: 30);
  static const Duration sendTimeout = Duration(seconds: 30);

  late final Dio _dio;
  final AuthService _authService;
  final TokenStorage _tokenStorage;

  ApiClient(this._authService, this._tokenStorage) {
    _dio = Dio(BaseOptions(
      baseUrl: baseUrl,
      connectTimeout: connectTimeout,
      receiveTimeout: receiveTimeout,
      sendTimeout: sendTimeout,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-App-Version': '1.0.0',
        'X-Platform': Platform.isIOS ? 'ios' : 'android',
      },
    ));

    _setupInterceptors();
  }

  void _setupInterceptors() {
    _dio.interceptors.addAll([
      AuthInterceptor(_tokenStorage),
      TokenRefreshInterceptor(_authService, _tokenStorage, _dio),
      ErrorInterceptor(),
      CacheInterceptor(),
      LogInterceptor(
        request: true,
        requestHeader: true,
        requestBody: true,
        responseHeader: false,
        responseBody: true,
        error: true,
        logPrint: (obj) => debugPrint(obj.toString()),
      ),
    ]);
  }

  Dio get dio => _dio;
}
```

### 2.2 环境配置

```dart
enum AppEnvironment { dev, staging, prod }

class AppConfig {
  final AppEnvironment env;
  final String apiBaseUrl;
  final String wsUrl;
  final bool enableLogging;

  const AppConfig({
    required this.env,
    required this.apiBaseUrl,
    required this.wsUrl,
    required this.enableLogging,
  });

  static const AppConfig dev = AppConfig(
    env: AppEnvironment.dev,
    apiBaseUrl: 'http://192.168.1.100:8000',
    wsUrl: 'ws://192.168.1.100:8000/ws',
    enableLogging: true,
  );

  static const AppConfig staging = AppConfig(
    env: AppEnvironment.staging,
    apiBaseUrl: 'https://staging-api.homecare.example.com',
    wsUrl: 'wss://staging-api.homecare.example.com/ws',
    enableLogging: true,
  );

  static const AppConfig prod = AppConfig(
    env: AppEnvironment.prod,
    apiBaseUrl: 'https://api.homecare.example.com',
    wsUrl: 'wss://api.homecare.example.com/ws',
    enableLogging: false,
  );
}
```

## 3. 拦截器

### 3.1 AuthInterceptor

```dart
class AuthInterceptor extends Interceptor {
  final TokenStorage _tokenStorage;

  AuthInterceptor(this._tokenStorage);

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final token = _tokenStorage.accessToken;
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    super.onRequest(options, handler);
  }
}
```

### 3.2 TokenRefreshInterceptor

```dart
class TokenRefreshInterceptor extends Interceptor {
  final AuthService _authService;
  final TokenStorage _tokenStorage;
  final Dio _dio;
  bool _isRefreshing = false;
  final Queue<RequestInterceptorHandler> _pendingHandlers = Queue();

  TokenRefreshInterceptor(this._authService, this._tokenStorage, this._dio);

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    if (err.response?.statusCode == 401 && !_isTokenRefreshRequest(err)) {
      if (!_isRefreshing) {
        _isRefreshing = true;
        try {
          final newToken = await _authService.refreshToken(
            _tokenStorage.refreshToken!,
          );
          await _tokenStorage.saveAccessToken(newToken);
          _isRefreshing = false;
          _retryPendingRequests(newToken);
        } catch (e) {
          _isRefreshing = false;
          _failPendingRequests(e);
          _authService.logout();
          return handler.next(err);
        }
      }

      // 重试当前请求
      err.requestOptions.headers['Authorization'] =
          'Bearer ${_tokenStorage.accessToken}';
      try {
        final response = await _dio.fetch(err.requestOptions);
        return handler.resolve(response);
      } catch (e) {
        return handler.next(err);
      }
    }
    super.onError(err, handler);
  }

  bool _isTokenRefreshRequest(DioException err) {
    return err.requestOptions.path.contains('/auth/refresh');
  }

  void _retryPendingRequests(String token) {
    while (_pendingHandlers.isNotEmpty) {
      final handler = _pendingHandlers.removeFirst();
      // 重试逻辑
    }
  }

  void _failPendingRequests(Object error) {
    while (_pendingHandlers.isNotEmpty) {
      final handler = _pendingHandlers.removeFirst();
      handler.next(DioException(
        requestOptions: RequestOptions(path: ''),
        error: error,
      ));
    }
  }
}
```

### 3.3 ErrorInterceptor

```dart
class ErrorInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final AppException exception = _mapToAppException(err);
    handler.next(DioException(
      requestOptions: err.requestOptions,
      response: err.response,
      error: exception,
      type: err.type,
    ));
  }

  AppException _mapToAppException(DioException err) {
    switch (err.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return NetworkException(
          code: 'TIMEOUT',
          message: '网络连接超时，请检查网络后重试',
        );
      case DioExceptionType.connectionError:
        return NetworkException(
          code: 'NO_CONNECTION',
          message: '网络连接失败，请检查网络设置',
        );
      case DioExceptionType.badResponse:
        return _handleHttpError(err.response!);
      case DioExceptionType.cancel:
        return AppException(
          code: 'CANCELLED',
          message: '请求已取消',
        );
      default:
        return AppException(
          code: 'UNKNOWN',
          message: '发生未知错误，请稍后重试',
        );
    }
  }

  AppException _handleHttpError(Response response) {
    final statusCode = response.statusCode;
    final data = response.data;
    final message = data is Map ? data['message'] ?? '请求失败' : '请求失败';

    switch (statusCode) {
      case 400:
        return ValidationException(code: 'VALIDATION', message: message);
      case 401:
        return AuthException(code: 'UNAUTHORIZED', message: '登录已过期，请重新登录');
      case 403:
        return PermissionException(code: 'FORBIDDEN', message: '无权限执行此操作');
      case 404:
        return NotFoundException(code: 'NOT_FOUND', message: '资源不存在');
      case 409:
        return ConflictException(code: 'CONFLICT', message: '数据冲突，请刷新后重试');
      case 429:
        return RateLimitException(code: 'RATE_LIMITED', message: '请求过于频繁，请稍后再试');
      case 500:
      case 502:
      case 503:
        return ServerException(code: 'SERVER_ERROR', message: '服务器繁忙，请稍后重试');
      default:
        return AppException(code: 'HTTP_$statusCode', message: message);
    }
  }
}
```

### 3.4 CacheInterceptor

```dart
class CacheInterceptor extends Interceptor {
  final CacheStore _cacheStore;
  final Duration defaultCacheDuration = const Duration(minutes: 5);

  CacheInterceptor(this._cacheStore);

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    if (options.method == 'GET') {
      final cacheKey = _generateCacheKey(options);
      final cached = _cacheStore.get(cacheKey);
      if (cached != null && !_isExpired(cached)) {
        return handler.resolve(Response(
          requestOptions: options,
          data: cached.data,
          statusCode: 200,
          headers: Headers.fromMap({'X-Cache': 'HIT'}),
        ));
      }
    }
    super.onRequest(options, handler);
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    if (response.requestOptions.method == 'GET' &&
        response.statusCode == 200) {
      final cacheKey = _generateCacheKey(response.requestOptions);
      _cacheStore.put(cacheKey, CacheEntry(
        data: response.data,
        timestamp: DateTime.now(),
        duration: defaultCacheDuration,
      ));
    }
    super.onResponse(response, handler);
  }

  String _generateCacheKey(RequestOptions options) {
    return '${options.method}:${options.uri}';
  }

  bool _isExpired(CacheEntry entry) {
    return DateTime.now().difference(entry.timestamp) > entry.duration;
  }
}
```

## 4. 异常体系

### 4.1 异常基类

```dart
class AppException implements Exception {
  final String code;
  final String message;
  final StackTrace? stackTrace;

  const AppException({
    required this.code,
    required this.message,
    this.stackTrace,
  });

  @override
  String toString() => '[$code] $message';
}

class NetworkException extends AppException {
  const NetworkException({required super.code, required super.message});
}

class AuthException extends AppException {
  const AuthException({required super.code, required super.message});
}

class ValidationException extends AppException {
  final Map<String, List<String>>? fieldErrors;
  const ValidationException({
    required super.code,
    required super.message,
    this.fieldErrors,
  });
}

class ServerException extends AppException {
  const ServerException({required super.code, required super.message});
}
```

### 4.2 全局错误处理

```dart
Future<T> safeApiCall<T>(Future<T> Function() action) async {
  try {
    return await action();
  } on AppException catch (e) {
    _handleAppException(e);
    rethrow;
  } on DioException catch (e) {
    final exception = e.error is AppException
        ? e.error as AppException
        : AppException(code: 'UNKNOWN', message: e.message ?? '未知错误');
    _handleAppException(exception);
    throw exception;
  } catch (e) {
    final exception = AppException(code: 'UNKNOWN', message: e.toString());
    _handleAppException(exception);
    throw exception;
  }
}

void _handleAppException(AppException e) {
  // 全局错误处理
  if (e is AuthException) {
    // 跳转到登录页
    navigatorKey.currentState?.pushNamedAndRemoveUntil('/login', (r) => false);
  }
  // 显示错误提示
  SnackBarService.showError(e.message);
}
```

## 5. 重试机制

### 5.1 重试策略

```dart
class RetryPolicy {
  final int maxRetries;
  final Duration initialDelay;
  final double backoffFactor;
  final Duration maxDelay;

  const RetryPolicy({
    this.maxRetries = 3,
    this.initialDelay = const Duration(seconds: 1),
    this.backoffFactor = 2.0,
    this.maxDelay = const Duration(seconds: 30),
  });

  Duration getDelay(int attempt) {
    final delay = initialDelay * (pow(backoffFactor, attempt) as num);
    return delay > maxDelay ? maxDelay : delay as Duration;
  }

  bool shouldRetry(DioException error, int attempt) {
    if (attempt >= maxRetries) return false;
    // 只对网络错误和 5xx 重试
    return error.type == DioExceptionType.connectionError ||
        error.type == DioExceptionType.connectionTimeout ||
        (error.response?.statusCode ?? 0) >= 500;
  }
}

class RetryInterceptor extends Interceptor {
  final RetryPolicy policy;
  final Dio dio;

  RetryInterceptor(this.policy, this.dio);

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    int attempt = 0;
    while (policy.shouldRetry(err, attempt)) {
      await Future.delayed(policy.getDelay(attempt));
      try {
        final response = await dio.fetch(err.requestOptions);
        return handler.resolve(response);
      } on DioException catch (e) {
        err = e;
        attempt++;
      }
    }
    super.onError(err, handler);
  }
}
```

## 6. 文件上传下载

### 6.1 文件上传

```dart
Future<UploadResult> uploadFile(
  String filePath, {
  required String memberId,
  ProgressCallback? onSendProgress,
}) async {
  final formData = FormData.fromMap({
    'file': await MultipartFile.fromFile(filePath),
    'member_id': memberId,
  });

  final response = await _dio.post(
    '/files/upload',
    data: formData,
    onSendProgress: onSendProgress,
  );

  return UploadResult.fromJson(response.data);
}
```

### 6.2 文件下载

```dart
Future<void> downloadFile(
  String url,
  String savePath, {
  ProgressCallback? onReceiveProgress,
}) async {
  await _dio.download(
    url,
    savePath,
    onReceiveProgress: onReceiveProgress,
  );
}
```

## 7. 网络层检查清单

- [ ] Dio 基础配置统一
- [ ] Token 自动附加
- [ ] Token 过期自动刷新
- [ ] 刷新期间请求排队
- [ ] 错误统一转换为 AppException
- [ ] 网络错误友好提示
- [ ] GET 请求缓存
- [ ] 缓存过期策略合理
- [ ] 网络错误自动重试
- [ ] 重试指数退避
- [ ] 文件上传进度回调
- [ ] 请求日志完整
- [ ] 环境配置分离
- [ ] 证书校验（生产环境）

---

*网络层是 APP 的血管。稳定、高效、容错的网络层，让用户在任何网络环境下都能流畅使用。*
