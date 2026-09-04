# 后端API限流与熔断详解

> 本文档是家健镜系统后端 API 限流与熔断的完整设计说明，覆盖限流算法、熔断器、降级策略、舱壁隔离、自适应保护。

## 1. 概述

### 1.1 设计目标

1. 防止系统过载
2. 保护核心服务
3. 快速失败
4. 自动恢复
5. 优雅降级

### 1.2 保护机制

| 机制 | 作用 | 触发条件 |
| --- | --- | --- |
| 限流 | 控制请求速率 | QPS 超过阈值 |
| 熔断 | 停止调用故障服务 | 错误率超过阈值 |
| 降级 | 返回备用结果 | 服务不可用 |
| 舱壁 | 隔离资源 | 资源耗尽 |
| 超时 | 快速失败 | 响应超时 |

## 2. 限流算法

### 2.1 固定窗口

```python
import time
from collections import defaultdict

class FixedWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(int)
        self.window_start = defaultdict(float)

    def allow(self, key: str) -> bool:
        now = time.time()
        current_window = int(now // self.window_seconds)

        if self.window_start[key] != current_window:
            self.window_start[key] = current_window
            self.requests[key] = 0

        if self.requests[key] < self.max_requests:
            self.requests[key] += 1
            return True
        return False
```

### 2.2 滑动窗口

```python
from collections import deque

class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        window = self.requests[key]

        # 移除过期请求
        while window and now - window[0] > self.window_seconds:
            window.popleft()

        if len(window) < self.max_requests:
            window.append(now)
            return True
        return False
```

### 2.3 令牌桶

```python
import threading

class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # 每秒生成令牌数
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def allow(self, tokens: int = 1) -> bool:
        with self.lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
```

### 2.4 漏桶

```python
class LeakyBucket:
    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # 每秒流出速率
        self.capacity = capacity
        self.water = 0
        self.last_leak = time.time()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            self._leak()
            if self.water < self.capacity:
                self.water += 1
                return True
            return False

    def _leak(self):
        now = time.time()
        elapsed = now - self.last_leak
        leaked = elapsed * self.rate
        self.water = max(0, self.water - leaked)
        self.last_leak = now
```

## 3. 分布式限流

### 3.1 Redis 限流

```python
import redis

class RedisRateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def allow(self, key: str, max_requests: int, window_seconds: int) -> bool:
        # Lua 脚本保证原子性
        lua_script = '''
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])

        local current = redis.call('INCR', key)
        if current == 1 then
            redis.call('EXPIRE', key, window)
        end

        if current > limit then
            return 0
        end
        return 1
        '''

        result = self.redis.eval(
            lua_script,
            1,
            f"rate_limit:{key}",
            max_requests,
            window_seconds,
            int(time.time()),
        )
        return result == 1
```

### 3.2 滑动窗口 Redis 实现

```python
class RedisSlidingWindowLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def allow(self, key: str, max_requests: int, window_seconds: int) -> bool:
        lua_script = '''
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        local member = ARGV[4]

        -- 移除过期成员
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window * 1000)

        -- 计数
        local count = redis.call('ZCARD', key)

        if count < limit then
            redis.call('ZADD', key, now, member)
            redis.call('EXPIRE', key, window)
            return 1
        end
        return 0
        '''

        result = self.redis.eval(
            lua_script,
            1,
            f"sliding_window:{key}",
            max_requests,
            window_seconds,
            int(time.time() * 1000),
            f"{time.time()}-{uuid.uuid4().hex}",
        )
        return result == 1
```

## 4. 熔断器

### 4.1 熔断器状态机

```python
class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max_calls: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = "closed"  # closed, open, half_open
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_calls = 0

    def call(self, func, *args, **kwargs):
        self._transition_state()

        if self.state == "open":
            raise CircuitBreakerOpenError("熔断器已打开")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _transition_state(self):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half_open"
                self.half_open_calls = 0

    def _on_success(self):
        if self.state == "half_open":
            self.half_open_calls += 1
            if self.half_open_calls >= self.half_open_max_calls:
                self.state = "closed"
                self.failure_count = 0
        else:
            self.failure_count = 0

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == "half_open":
            self.state = "open"
        elif self.failure_count >= self.failure_threshold:
            self.state = "open"
```

### 4.2 熔断器装饰器

```python
def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: int = 30,
    fallback=None,
):
    breaker = CircuitBreaker(failure_threshold, recovery_timeout)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return breaker.call(func, *args, **kwargs)
            except CircuitBreakerOpenError:
                if fallback:
                    return fallback(*args, **kwargs)
                raise
        return wrapper
    return decorator

# 使用
@circuit_breaker(failure_threshold=3, recovery_timeout=10, fallback=get_medicine_cache)
async def get_medicine_from_api(medicine_id: str):
    return await api.get_medicine(medicine_id)
```

## 5. 降级策略

### 5.1 降级类型

```python
class DegradationStrategy:
    @staticmethod
    def return_default(default_value):
        '''返回默认值'''
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    return default_value
            return wrapper
        return decorator

    @staticmethod
    def return_cache(cache_key: str, cache_client):
        '''返回缓存数据'''
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    cached = cache_client.get(cache_key)
                    if cached:
                        return json.loads(cached)
                    raise
            return wrapper
        return decorator

    @staticmethod
    def return_stub(stub_data):
        '''返回桩数据'''
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    return stub_data
            return wrapper
        return decorator
```

### 5.2 降级开关

```python
class DegradationManager:
    def __init__(self, redis_client):
        self.redis = redis_client

    def is_degraded(self, service: str) -> bool:
        return self.redis.get(f"degradation:{service}") == b"1"

    def enable_degradation(self, service: str, ttl: int = 300):
        self.redis.setex(f"degradation:{service}", ttl, "1")

    def disable_degradation(self, service: str):
        self.redis.delete(f"degradation:{service}")

    def get_degraded_services(self) -> list[str]:
        keys = self.redis.keys("degradation:*")
        return [k.decode().split(":")[1] for k in keys]
```

## 6. 舱壁隔离

### 6.1 线程池隔离

```python
from concurrent.futures import ThreadPoolExecutor

class Bulkhead:
    def __init__(self, max_concurrent: int, max_queue: int = 100):
        self.executor = ThreadPoolExecutor(
            max_workers=max_concurrent,
        )
        self.semaphore = threading.Semaphore(max_concurrent)
        self.max_queue = max_queue
        self.queue_size = 0

    def execute(self, func, *args, **kwargs):
        if not self.semaphore.acquire(blocking=False):
            if self.queue_size >= self.max_queue:
                raise BulkheadFullError("舱壁已满")
            self.queue_size += 1

        try:
            future = self.executor.submit(func, *args, **kwargs)
            return future.result(timeout=5)
        finally:
            self.semaphore.release()
            if self.queue_size > 0:
                self.queue_size -= 1
```

### 6.2 信号量隔离

```python
class SemaphoreBulkhead:
    def __init__(self, max_concurrent: int):
        self.semaphore = threading.Semaphore(max_concurrent)

    def execute(self, func, *args, **kwargs):
        acquired = self.semaphore.acquire(blocking=False)
        if not acquired:
            raise BulkheadFullError("并发数超限")

        try:
            return func(*args, **kwargs)
        finally:
            self.semaphore.release()
```

## 7. 自适应保护

### 7.1 自适应限流

```python
class AdaptiveRateLimiter:
    def __init__(self, initial_rate: int = 100):
        self.current_rate = initial_rate
        self.min_rate = 10
        self.max_rate = 1000
        self.error_rate_window = []

    def adjust(self, error_rate: float, latency_p99: float):
        # 错误率高，降低限流
        if error_rate > 0.1:
            self.current_rate = max(self.min_rate, int(self.current_rate * 0.8))
        # 延迟高，降低限流
        elif latency_p99 > 1.0:
            self.current_rate = max(self.min_rate, int(self.current_rate * 0.9))
        # 系统健康，提高限流
        elif error_rate < 0.01 and latency_p99 < 0.2:
            self.current_rate = min(self.max_rate, int(self.current_rate * 1.1))
```

## 8. 限流熔断检查清单

- [ ] 固定窗口
- [ ] 滑动窗口
- [ ] 令牌桶
- [ ] 漏桶
- [ ] Redis 分布式限流
- [ ] 熔断器
- [ ] 降级策略
- [ ] 降级开关
- [ ] 线程池隔离
- [ ] 信号量隔离
- [ ] 自适应限流
- [ ] 监控告警

---

*限流熔断是系统的安全阀。智能保护、优雅降级，让系统在压力下依然稳定。*
