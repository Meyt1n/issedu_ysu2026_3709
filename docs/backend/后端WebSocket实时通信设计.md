# 后端WebSocket实时通信设计

> 本文档是家健镜系统 WebSocket 实时通信的完整设计说明，覆盖连接管理、消息协议、心跳机制、断线重连。

## 1. WebSocket 概述

### 1.1 设计目标

1. 实时通信：消息即时送达
2. 低延迟：毫秒级响应
3. 高并发：支持大量连接
4. 可靠传输：消息不丢失
5. 断线重连：网络恢复后自动重连

### 1.2 使用场景

| 场景 | 说明 |
| --- | --- |
| 健康助手对话 | 实时对话和流式输出 |
| 风险预警推送 | 实时推送健康风险 |
| 用药提醒 | 实时提醒 |
| 数据同步 | 多端实时同步 |
| 设备状态 | 设备在线状态实时更新 |

## 2. 连接管理

### 2.1 连接建立

```python
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(message)

    async def broadcast(self, message: dict):
        for connections in self.active_connections.values():
            for connection in connections:
                await connection.send_json(message)

manager = ConnectionManager()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    # 1. 认证
    token = websocket.query_params.get("token")
    user = await auth_service.verify_token(token)
    if not user:
        await websocket.close(code=4001)
        return

    # 2. 建立连接
    await manager.connect(websocket, user_id)

    try:
        while True:
            data = await websocket.receive_json()
            await handle_message(websocket, data, user)
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
```

### 2.2 认证鉴权

```python
class WebSocketAuth:
    @staticmethod
    async def authenticate(websocket):
        # 从 query 参数获取 token
        token = websocket.query_params.get("token")
        if not token:
            return None

        # 验证 token
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            return payload["user_id"]
        except JWTError:
            return None
```

## 3. 消息协议

### 3.1 消息格式

```json
{
  "type": "message",
  "id": "msg_001",
  "timestamp": "2026-09-04T10:00:00Z",
  "data": {
    "content": "你好"
  }
}
```

### 3.2 消息类型

| 类型 | 说明 | 方向 |
| --- | --- | --- |
| ping | 心跳 | 双向 |
| pong | 心跳响应 | 双向 |
| message | 聊天消息 | 双向 |
| typing | 正在输入 | 客户端 -> 服务端 |
| risk_alert | 风险预警 | 服务端 -> 客户端 |
| medication_reminder | 用药提醒 | 服务端 -> 客户端 |
| sync | 数据同步 | 双向 |
| error | 错误消息 | 服务端 -> 客户端 |

### 3.3 消息处理

```python
async def handle_message(websocket, data, user):
    msg_type = data.get("type")

    handlers = {
        "ping": handle_ping,
        "message": handle_chat_message,
        "typing": handle_typing,
        "sync": handle_sync,
    }

    handler = handlers.get(msg_type)
    if handler:
        await handler(websocket, data, user)
    else:
        await websocket.send_json({
            "type": "error",
            "error": f"未知消息类型: {msg_type}",
        })

async def handle_ping(websocket, data, user):
    await websocket.send_json({"type": "pong", "timestamp": data.get("timestamp")})
```

## 4. 心跳机制

### 4.1 服务端心跳

```python
async def heartbeat(websocket, user_id):
    while True:
        try:
            await asyncio.sleep(30)  # 每 30 秒发送心跳
            await websocket.send_json({"type": "ping"})
        except Exception:
            break
```

### 4.2 客户端心跳

```dart
class WebSocketClient {
  WebSocket? _socket;
  Timer? _heartbeatTimer;
  int _missedPongs = 0;

  void _startHeartbeat() {
    _heartbeatTimer = Timer.periodic(Duration(seconds: 25), (_) {
      _socket?.add(jsonEncode({'type': 'ping'}));
      _missedPongs++;
      if (_missedPongs > 3) {
        _reconnect();
      }
    });
  }

  void _handlePong() {
    _missedPongs = 0;
  }
}
```

## 5. 断线重连

### 5.1 重连策略

```dart
class ReconnectStrategy {
  int _attempts = 0;
  final int _maxAttempts = 10;

  Duration get nextDelay {
    final base = Duration(seconds: 1);
    final delay = base * pow(2, _attempts).toInt();
    return delay > Duration(seconds: 60) ? Duration(seconds: 60) : delay;
  }

  Future<void> reconnect() async {
    if (_attempts >= _maxAttempts) {
      // 通知用户连接失败
      return;
    }

    await Future.delayed(nextDelay);
    _attempts++;
    // 尝试重连
  }

  void reset() {
    _attempts = 0;
  }
}
```

### 5.2 消息补发

```python
class MessageQueue:
    def __init__(self, redis):
        self.redis = redis

    async def enqueue(self, user_id, message):
        await self.redis.rpush(f"mq:{user_id}", json.dumps(message))

    async def dequeue_all(self, user_id):
        messages = []
        while True:
            msg = await self.redis.lpop(f"mq:{user_id}")
            if not msg:
                break
            messages.append(json.loads(msg))
        return messages

    async def on_connect(self, user_id, websocket):
        # 连接后补发离线消息
        messages = await self.dequeue_all(user_id)
        for msg in messages:
            await websocket.send_json(msg)
```

## 6. 房间管理

### 6.1 多房间

```python
class RoomManager:
    def __init__(self):
        self.rooms: dict[str, set[str]] = {}  # room_id -> {user_id}

    async def join_room(self, room_id, user_id, websocket):
        if room_id not in self.rooms:
            self.rooms[room_id] = set()
        self.rooms[room_id].add(user_id)

    async def leave_room(self, room_id, user_id):
        if room_id in self.rooms:
            self.rooms[room_id].discard(user_id)

    async def send_to_room(self, room_id, message):
        if room_id in self.rooms:
            for user_id in self.rooms[room_id]:
                await manager.send_personal_message(message, user_id)
```

## 7. 性能优化

### 7.1 连接数限制

```python
MAX_CONNECTIONS_PER_USER = 5

async def connect(self, websocket, user_id):
    connections = self.active_connections.get(user_id, [])
    if len(connections) >= MAX_CONNECTIONS_PER_USER:
        # 关闭最早的连接
        oldest = connections[0]
        await oldest.close(code=4002)
```

### 7.2 消息压缩

```python
import zlib

async def send_compressed(websocket, message):
    data = json.dumps(message).encode()
    compressed = zlib.compress(data)
    await websocket.send_bytes(compressed)
```

## 8. WebSocket检查清单

- [ ] 连接管理
- [ ] 认证鉴权
- [ ] 消息协议
- [ ] 心跳机制
- [ ] 断线重连
- [ ] 消息补发
- [ ] 房间管理
- [ ] 连接数限制
- [ ] 消息压缩
- [ ] 错误处理
- [ ] 监控告警
- [ ] 性能优化

---

*WebSocket 是实时通信的桥梁。低延迟、高可靠的实时连接，让健康服务触手可及。*
