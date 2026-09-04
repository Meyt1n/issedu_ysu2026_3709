# 后端API网关设计

> 本文档是家健镜系统 API 网关的完整设计说明，覆盖路由转发、认证鉴权、限流熔断、日志监控。

## 1. 网关概述

### 1.1 设计目标

1. 统一入口：所有 API 请求经过网关
2. 安全防护：认证、鉴权、限流
3. 路由转发：动态路由到后端服务
4. 协议转换：HTTP/WebSocket 等
5. 可观测：请求日志和监控

### 1.2 网关功能

| 功能 | 说明 |
| --- | --- |
| 路由转发 | 根据路径转发到对应服务 |
| 负载均衡 | 多实例负载均衡 |
| 认证鉴权 | JWT 验证和权限检查 |
| 限流熔断 | 防止流量过载 |
| 请求改写 | Header、参数改写 |
| 响应改写 | 统一响应格式 |
| 日志记录 | 请求日志和审计 |
| 监控指标 | 性能指标收集 |
| 缓存 | 响应缓存 |
| CORS | 跨域处理 |

## 2. 路由设计

### 2.1 路由规则

```yaml
routes:
  - path: /api/v1/auth/**
    service: auth-service
    strip_prefix: false
  - path: /api/v1/medicines/**
    service: medicine-service
    strip_prefix: false
  - path: /api/v1/health/**
    service: health-service
    strip_prefix: false
  - path: /api/v1/risks/**
    service: risk-service
    strip_prefix: false
  - path: /api/v1/chat/**
    service: chat-service
    strip_prefix: false
  - path: /ws/**
    service: websocket-service
    strip_prefix: false
    protocols: [websocket]
```

### 2.2 负载均衡

```python
class LoadBalancer:
    def __init__(self, strategy="round_robin"):
        self.strategy = strategy
        self.servers = {}
        self.counter = 0

    def add_server(self, service, server):
        if service not in self.servers:
            self.servers[service] = []
        self.servers[service].append(server)

    def get_server(self, service):
        servers = self.servers.get(service, [])
        if not servers:
            return None

        if self.strategy == "round_robin":
            server = servers[self.counter % len(servers)]
            self.counter += 1
            return server
        elif self.strategy == "random":
            return random.choice(servers)
        elif self.strategy == "least_connections":
            return min(servers, key=lambda s: s.connections)
```

## 3. 认证鉴权

### 3.1 JWT 验证

```python
class AuthMiddleware:
    def __init__(self, jwt_secret, public_paths=None):
        self.jwt_secret = jwt_secret
        self.public_paths = public_paths or []

    async def __call__(self, request, call_next):
        # 公开路径跳过认证
        if self._is_public(request.url.path):
            return await call_next(request)

        # 验证 Token
        token = self._extract_token(request)
        if not token:
            return JSONResponse(status_code=401, content={"error": "未登录"})

        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            request.state.user = payload
        except JWTError:
            return JSONResponse(status_code=401, content={"error": "Token 无效"})

        return await call_next(request)

    def _extract_token(self, request):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return None

    def _is_public(self, path):
        for pattern in self.public_paths:
            if path.startswith(pattern):
                return True
        return False
```

### 3.2 权限检查

```python
class PermissionMiddleware:
    def __init__(self, permission_map):
        self.permission_map = permission_map

    async def __call__(self, request, call_next):
        user = request.state.user
        path = request.url.path
        method = request.method

        required_permission = self._get_required_permission(path, method)
        if required_permission and required_permission not in user.get("permissions", []):
            return JSONResponse(status_code=403, content={"error": "无权限"})

        return await call_next(request)
```

## 4. 限流熔断

### 4.1 限流

```python
class RateLimitMiddleware:
    def __init__(self, redis, default_limit=100, default_window=60):
        self.redis = redis
        self.default_limit = default_limit
        self.default_window = default_window

    async def __call__(self, request, call_next):
        user_id = request.state.user.get("id", "anonymous")
        path = request.url.path
        key = f"rate_limit:{user_id}:{path}"

        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, self.default_window)

        if count > self.default_limit:
            return JSONResponse(
                status_code=429,
                content={"error": "请求过于频繁"},
                headers={"Retry-After": str(self.default_window)},
            )

        return await call_next(request)
```

### 4.2 熔断

```python
class CircuitBreakerMiddleware:
    def __init__(self, failure_threshold=5, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.states = {}  # service -> state

    async def __call__(self, request, call_next):
        service = self._get_service(request)
        state = self.states.get(service, {"failures": 0, "last_failure": None, "open": False})

        if state["open"]:
            if time.time() - state["last_failure"] > self.recovery_timeout:
                state["open"] = False  # 半开
            else:
                return JSONResponse(status_code=503, content={"error": "服务暂不可用"})

        try:
            response = await call_next(request)
            if response.status_code >= 500:
                self._record_failure(service, state)
            else:
                state["failures"] = 0
            return response
        except Exception:
            self._record_failure(service, state)
            raise

    def _record_failure(self, service, state):
        state["failures"] += 1
        state["last_failure"] = time.time()
        if state["failures"] >= self.failure_threshold:
            state["open"] = True
```

## 5. 日志监控

### 5.1 请求日志

```python
class LoggingMiddleware:
    async def __call__(self, request, call_next):
        start_time = time.time()

        response = await call_next(request)

        duration = (time.time() - start_time) * 1000
        logger.info(
            f"{request.method} {request.url.path} "
            f"{response.status_code} {duration:.0f}ms",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration,
                "user_id": getattr(request.state, "user", {}).get("id"),
                "ip": request.client.host,
            },
        )

        return response
```

### 5.2 监控指标

```python
class MetricsMiddleware:
    def __init__(self):
        self.request_count = Counter("http_requests_total", ["method", "path", "status"])
        self.request_duration = Histogram("http_request_duration_seconds", ["method", "path"])

    async def __call__(self, request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time

        self.request_count.labels(
            request.method, request.url.path, response.status_code
        ).inc()
        self.request_duration.labels(
            request.method, request.url.path
        ).observe(duration)

        return response
```

## 6. 网关检查清单

- [ ] 路由转发
- [ ] 负载均衡
- [ ] 认证鉴权
- [ ] 限流
- [ ] 熔断
- [ ] 请求改写
- [ ] 响应改写
- [ ] 日志记录
- [ ] 监控指标
- [ ] CORS 处理
- [ ] WebSocket 支持
- [ ] 健康检查

---

*API 网关是系统的门户。安全、高效、可观测的网关，让所有 API 请求有序可控。*
