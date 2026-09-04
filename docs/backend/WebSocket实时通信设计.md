# WebSocket实时通信设计

> 本文档是家健镜系统 WebSocket 实时通信的完整设计说明，覆盖连接管理、消息协议、事件推送、心跳保活、重连机制、权限控制。面向后端开发者，作为实时通信实现的权威依据。

## 1. 实时通信概述

### 1.1 设计目标

1. **低延迟**：健康事件实时推送到客户端
2. **可靠**：消息不丢失、不重复
3. **可扩展**：支持多实例部署
4. **安全**：连接需要认证，消息需要授权
5. **优雅降级**：WebSocket 不可用时降级到轮询

### 1.2 使用场景

| 场景 | 说明 |
| --- | --- |
| 健康事件推送 | 用药提醒、风险提醒实时推送 |
| 任务状态更新 | 视觉识别任务进度实时更新 |
| 对话消息 | 健康助手对话实时回复 |
| 设备状态 | 智能设备状态变化通知 |
| 家庭同步 | 多设备间数据同步通知 |

### 1.3 技术选型

- **WebSocket**：标准 WebSocket 协议（RFC 6455）
- **传输格式**：JSON
- **心跳**：客户端每 30 秒发送 ping，服务端 60 秒超时断开
- **重连**：指数退避，最大间隔 30 秒

## 2. 连接管理

### 2.1 连接建立

```
客户端 → 服务端：GET /ws/v1/connect?token=<JWT>
服务端 → 客户端：101 Switching Protocols
服务端 → 客户端：{"type":"connected","connection_id":"...","server_time":...}
```

### 2.2 认证

```python
class WebSocketAuth:
    async def authenticate(self, websocket: WebSocket):
        # 从 query 参数获取 token
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4401, reason="未认证")
            return None

        try:
            payload = verify_jwt(token)
            return payload
        except ExpiredSignatureError:
            await websocket.close(code=4401, reason="Token已过期")
            return None
        except InvalidTokenError:
            await websocket.close(code=4401, reason="Token无效")
            return None
```

### 2.3 连接表

```sql
CREATE TABLE ws_connections (
    connection_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    household_id UUID,
    device_id VARCHAR(100),
    ip_address INET,
    user_agent TEXT,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_ping_at TIMESTAMPTZ,
    disconnected_at TIMESTAMPTZ,
    disconnect_reason VARCHAR(50),
    server_instance VARCHAR(100)
);
```

### 2.4 连接管理器

```python
class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, WebSocket] = {}  # connection_id -> websocket
        self.user_connections: dict[str, set[str]] = {}  # user_id -> set of connection_id
        self.household_connections: dict[str, set[str]] = {}  # household_id -> set of connection_id

    async def connect(self, websocket: WebSocket, user_id: str, household_id: str | None):
        connection_id = str(uuid.uuid4())
        await websocket.accept()

        self.connections[connection_id] = websocket
        self.user_connections.setdefault(user_id, set()).add(connection_id)
        if household_id:
            self.household_connections.setdefault(household_id, set()).add(connection_id)

        # 发送连接确认
        await websocket.send_json({
            "type": "connected",
            "connection_id": connection_id,
            "server_time": datetime.now().isoformat(),
        })

        return connection_id

    async def disconnect(self, connection_id: str, user_id: str, household_id: str | None):
        self.connections.pop(connection_id, None)
        self.user_connections.get(user_id, set()).discard(connection_id)
        if household_id:
            self.household_connections.get(household_id, set()).discard(connection_id)
```

## 3. 消息协议

### 3.1 消息格式

```json
{
  "type": "event",
  "message_id": "uuid",
  "timestamp": "2026-09-04T10:00:00Z",
  "payload": {}
}
```

### 3.2 消息类型

| type | 方向 | 说明 |
| --- | --- | --- |
| connected | S→C | 连接建立确认 |
| ping | C→S | 心跳 |
| pong | S→C | 心跳响应 |
| event | S→C | 事件推送 |
| task_update | S→C | 任务状态更新 |
| chat_message | S→C | 对话消息 |
| chat_delta | S→C | 对话流式增量 |
| error | S→C | 错误 |
| subscribe | C→S | 订阅主题 |
| unsubscribe | C→S | 取消订阅 |

### 3.3 事件推送消息

```json
{
  "type": "event",
  "message_id": "a1b2c3d4-...",
  "timestamp": "2026-09-04T10:00:00Z",
  "payload": {
    "event_id": "e5f6g7h8-...",
    "event_type": "medication_reminder",
    "member_id": "m1n2o3p4-...",
    "member_name": "张三",
    "title": "用药提醒",
    "description": "该服用阿莫西林了",
    "data": {
      "medicine_name": "阿莫西林",
      "dosage": "0.5g",
      "scheduled_time": "10:00"
    }
  }
}
```

### 3.4 任务更新消息

```json
{
  "type": "task_update",
  "message_id": "...",
  "timestamp": "...",
  "payload": {
    "task_id": "v1w2x3y4-...",
    "task_type": "vision_recognition",
    "status": "MATCHED",
    "progress": 100,
    "result": {
      "medicine_name": "阿莫西林",
      "specification": "0.25g*24粒",
      "confidence": 0.92
    }
  }
}
```

## 4. 事件推送

### 4.1 推送流程

```python
class EventPusher:
    def __init__(self, connection_manager: ConnectionManager, redis: Redis):
        self.manager = connection_manager
        self.redis = redis

    async def push_to_user(self, user_id: str, message: dict):
        # 1. 本地连接直接推送
        connection_ids = self.manager.user_connections.get(user_id, set())
        for cid in connection_ids:
            ws = self.manager.connections.get(cid)
            if ws:
                try:
                    await ws.send_json(message)
                except Exception:
                    await self.manager.disconnect(cid, user_id, None)

        # 2. 通过 Redis 发布到其他实例
        await self.redis.publish("ws:user:" + user_id, json.dumps(message))

    async def push_to_household(self, household_id: str, message: dict):
        connection_ids = self.manager.household_connections.get(household_id, set())
        for cid in connection_ids:
            ws = self.manager.connections.get(cid)
            if ws:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

        await self.redis.publish("ws:household:" + household_id, json.dumps(message))
```

### 4.2 多实例同步（Redis Pub/Sub）

```python
class RedisPubSub:
    async def start(self):
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe("ws:user:*", "ws:household:*")

        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                channel = message["channel"].decode()
                data = json.loads(message["data"])

                if channel.startswith("ws:user:"):
                    user_id = channel.split(":", 2)[2]
                    await self._deliver_to_local(user_id, data, scope="user")
                elif channel.startswith("ws:household:"):
                    household_id = channel.split(":", 2)[2]
                    await self._deliver_to_local(household_id, data, scope="household")
```

### 4.3 事件写入后推送

```python
# 在事件创建服务中
async def create_event_and_push(event: HealthEvent, db: AsyncSession):
    # 1. 保存事件
    db.add(event)
    await db.commit()

    # 2. 推送到家庭所有成员
    message = {
        "type": "event",
        "message_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "payload": event_to_ws_payload(event),
    }
    await event_pusher.push_to_household(event.household_id, message)

    return event
```

## 5. 心跳与保活

### 5.1 心跳机制

```python
async def heartbeat_handler(websocket: WebSocket, connection_id: str):
    while True:
        try:
            # 等待客户端 ping（30 秒超时）
            message = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=30,
            )

            if message.get("type") == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat(),
                })
                # 更新最后心跳时间
                await update_last_ping(connection_id)
            elif message.get("type") == "subscribe":
                await handle_subscribe(websocket, message)
            elif message.get("type") == "unsubscribe":
                await handle_unsubscribe(websocket, message)

        except asyncio.TimeoutError:
            # 60 秒无心跳断开
            await websocket.close(code=4408, reason="心跳超时")
            break
        except WebSocketDisconnect:
            break
```

### 5.2 客户端重连

```javascript
// 客户端重连逻辑（指数退避）
class WSClient {
  constructor(url) {
    this.url = url;
    this.reconnectDelay = 1000;
    this.maxDelay = 30000;
    this.ws = null;
  }

  connect() {
    this.ws = new WebSocket(this.url);

    this.ws.onclose = () => {
      setTimeout(() => {
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxDelay);
        this.connect();
      }, this.reconnectDelay);
    };

    this.ws.onopen = () => {
      this.reconnectDelay = 1000; // 重置
      this.startHeartbeat();
    };
  }

  startHeartbeat() {
    setInterval(() => {
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);
  }
}
```

## 6. 消息可靠性

### 6.1 消息去重

```python
class MessageDeduplicator:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def is_duplicate(self, message_id: str, ttl: int = 300) -> bool:
        # 使用 Redis SETNX 去重
        key = f"ws:dedup:{message_id}"
        result = await self.redis.set(key, "1", ex=ttl, nx=True)
        return result is None  # None 表示已存在（重复）
```

### 6.2 消息确认（可选）

```json
// 客户端确认收到
{
  "type": "ack",
  "message_id": "a1b2c3d4-..."
}
```

### 6.3 离线消息

```python
class OfflineMessageStore:
    async def store(self, user_id: str, message: dict):
        # 存储到 Redis 列表，保留 24 小时
        key = f"ws:offline:{user_id}"
        await self.redis.lpush(key, json.dumps(message))
        await self.redis.expire(key, 86400)
        await self.redis.ltrim(key, 0, 99)  # 最多保留 100 条

    async def get_and_clear(self, user_id: str) -> list[dict]:
        key = f"ws:offline:{user_id}"
        messages = await self.redis.lrange(key, 0, -1)
        await self.redis.delete(key)
        return [json.loads(m) for m in messages]
```

## 7. 订阅机制

### 7.1 主题订阅

```json
// 客户端订阅
{
  "type": "subscribe",
  "topics": ["household:events", "task:vision:v1w2x3y4"]
}

// 服务端响应
{
  "type": "subscribed",
  "topics": ["household:events", "task:vision:v1w2x3y4"]
}
```

### 7.2 订阅管理

```python
class SubscriptionManager:
    def __init__(self):
        self.subscriptions: dict[str, set[str]] = {}  # connection_id -> set of topics

    async def subscribe(self, connection_id: str, topics: list[str]):
        # 验证权限
        for topic in topics:
            if not await self._check_permission(connection_id, topic):
                raise PermissionError(f"无权订阅 {topic}")

        self.subscriptions.setdefault(connection_id, set()).update(topics)

    async def _check_permission(self, connection_id: str, topic: str) -> bool:
        # household:events → 必须是该家庭成员
        if topic.startswith("household:"):
            household_id = topic.split(":")[1]
            return await is_household_member(connection_id, household_id)
        # task:vision:xxx → 必须是任务创建者
        if topic.startswith("task:"):
            task_id = topic.split(":")[2]
            return await is_task_owner(connection_id, task_id)
        return False
```

## 8. 流式对话

### 8.1 对话流式推送

```python
async def stream_chat_response(
    websocket: WebSocket,
    conversation_id: str,
    user_message: str,
):
    # 发送开始事件
    await websocket.send_json({
        "type": "chat_start",
        "conversation_id": conversation_id,
    })

    # 流式生成
    async for delta in llm_service.chat_stream(user_message):
        await websocket.send_json({
            "type": "chat_delta",
            "conversation_id": conversation_id,
            "delta": delta.content,
        })

    # 发送完成事件
    await websocket.send_json({
        "type": "chat_done",
        "conversation_id": conversation_id,
        "message_id": str(uuid.uuid4()),
        "citations": [...],
    })
```

## 9. 错误处理

### 9.1 关闭码

| 码 | 说明 |
| --- | --- |
| 1000 | 正常关闭 |
| 1001 | 客户端离开 |
| 4401 | 未认证 |
| 4403 | 无权限 |
| 4408 | 心跳超时 |
| 4429 | 请求过于频繁 |
| 4500 | 服务端错误 |

### 9.2 错误消息

```json
{
  "type": "error",
  "code": "RATE_LIMITED",
  "message": "请求过于频繁，请稍后再试",
  "retry_after": 30
}
```

## 10. 限流

### 10.1 连接限流

```python
class RateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def check_connection_limit(self, user_id: str, max_connections: int = 5):
        key = f"ws:conn_count:{user_id}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 3600)
        if count > max_connections:
            await self.redis.decr(key)
            return False
        return True

    async def release_connection(self, user_id: str):
        await self.redis.decr(f"ws:conn_count:{user_id}")
```

### 10.2 消息限流

```python
    async def check_message_rate(self, connection_id: str, max_per_minute: int = 60):
        key = f"ws:msg_rate:{connection_id}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 60)
        return count <= max_per_minute
```

## 11. 监控

### 11.1 监控指标

| 指标 | 说明 |
| --- | --- |
| ws_connections_total | 当前连接数 |
| ws_connections_new | 新建连接数 |
| ws_connections_closed | 关闭连接数 |
| ws_messages_sent | 发送消息数 |
| ws_messages_received | 接收消息数 |
| ws_heartbeat_timeouts | 心跳超时数 |
| ws_push_failures | 推送失败数 |

### 11.2 健康检查

```python
@app.get("/health/ws")
async def ws_health():
    return {
        "status": "ok",
        "connections": len(connection_manager.connections),
        "users": len(connection_manager.user_connections),
        "households": len(connection_manager.household_connections),
    }
```

## 12. WebSocket检查清单

- [ ] 连接需要 JWT 认证
- [ ] 心跳机制正常工作
- [ ] 超时自动断开
- [ ] 客户端重连指数退避
- [ ] 多实例 Redis 同步
- [ ] 消息去重
- [ ] 离线消息存储
- [ ] 订阅权限校验
- [ ] 流式对话正常
- [ ] 错误码规范
- [ ] 限流生效
- [ ] 监控指标完整
- [ ] 降级到轮询方案

---

*WebSocket 是实时体验的基石。低延迟、可靠、安全的实时通信，让健康提醒第一时间到达。*
