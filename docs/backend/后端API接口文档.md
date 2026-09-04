# 后端 API 接口文档

> 本文档是家健镜后端 API 的完整接口说明，覆盖所有端点的请求/响应格式、错误码、认证要求、示例。面向前后端开发者，作为联调和开发的权威依据。

## 1. 通用说明

### 1.1 Base URL

```
# 家庭部署
http://<server-ip>:18800/api/v1

# 生产部署
https://api.example.com/api/v1
```

### 1.2 认证

所有需要认证的接口使用 Bearer Token：

```
Authorization: Bearer <jwt-token>
```

Token 通过登录接口获取，有效期 24 小时。

### 1.3 请求 ID

每个响应包含 `X-Request-ID` 头，用于问题排查：

```
X-Request-ID: req_20260904_abc123def456
```

### 1.4 统一响应格式

**成功：**
```json
{
  "data": { ... },
  "request_id": "req_abc123"
}
```

**错误：**
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "参数校验失败",
    "details": { "field": "错误说明" }
  },
  "request_id": "req_abc123"
}
```

### 1.5 通用错误码

| HTTP | code | 说明 |
| --- | --- | --- |
| 400 | VALIDATION_ERROR | 请求参数校验失败 |
| 401 | UNAUTHORIZED | 未登录或 Token 过期 |
| 403 | ACCESS_DENIED | 无权限访问 |
| 404 | RESOURCE_NOT_FOUND | 资源不存在 |
| 409 | IDEMPOTENCY_KEY_CONFLICT | 幂等键冲突 |
| 409 | VERSION_CONFLICT | 乐观锁版本冲突 |
| 429 | RATE_LIMITED | 请求过于频繁 |
| 500 | INTERNAL_ERROR | 服务器内部错误 |
| 503 | SERVICE_UNAVAILABLE | 服务暂时不可用 |

## 2. 认证接口

### 2.1 登录

```
POST /auth/login
```

**请求体：**
```json
{
  "username": "zhangsan",
  "password": "MyPass123!"
}
```

**响应 200：**
```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 86400,
    "user": {
      "user_id": "u_001",
      "username": "zhangsan",
      "display_name": "张三"
    }
  }
}
```

**错误：**
- 401 `INVALID_CREDENTIALS`：用户名或密码错误

### 2.2 注册

```
POST /auth/register
```

**请求体：**
```json
{
  "username": "zhangsan",
  "password": "MyPass123!",
  "display_name": "张三"
}
```

**响应 201：**
```json
{
  "data": {
    "user_id": "u_002",
    "username": "zhangsan",
    "display_name": "张三",
    "created_at": "2026-09-04T10:00:00+08:00"
  }
}
```

### 2.3 修改密码

```
POST /auth/change-password
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "old_password": "OldPass123!",
  "new_password": "NewPass456!"
}
```

**响应 200：**
```json
{ "data": { "message": "密码修改成功" } }
```

修改密码后，该用户的其他所有会话失效。

### 2.4 获取当前用户

```
GET /auth/me
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "user_id": "u_001",
    "username": "zhangsan",
    "display_name": "张三",
    "households": [
      {
        "household_id": "h_001",
        "name": "我家",
        "role": "owner"
      }
    ]
  }
}
```

## 3. 家庭接口

### 3.1 创建家庭

```
POST /households
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "name": "我家",
  "timezone": "Asia/Shanghai"
}
```

**响应 201：**
```json
{
  "data": {
    "household_id": "h_001",
    "name": "我家",
    "timezone": "Asia/Shanghai",
    "role": "owner",
    "created_at": "2026-09-04T10:00:00+08:00"
  }
}
```

### 3.2 获取家庭列表

```
GET /households
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "households": [
      {
        "household_id": "h_001",
        "name": "我家",
        "timezone": "Asia/Shanghai",
        "role": "owner",
        "member_count": 3
      }
    ]
  }
}
```

### 3.3 获取家庭详情

```
GET /households/{household_id}
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "household_id": "h_001",
    "name": "我家",
    "timezone": "Asia/Shanghai",
    "created_by": "u_001",
    "created_at": "2026-09-01T10:00:00+08:00"
  }
}
```

### 3.4 更新家庭

```
PATCH /households/{household_id}
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "name": "我们家",
  "timezone": "Asia/Shanghai"
}
```

### 3.5 获取能力声明

```
GET /households/{household_id}/capabilities
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "capabilities": {
      "manual-health-event": { "status": "available" },
      "household-member": { "status": "available" },
      "field-authorization": { "status": "available" },
      "vision-task": { "status": "available" },
      "vision-inference": { "status": "available" },
      "knowledge-store": { "status": "available" },
      "local-assistant": { "status": "unavailable", "reason": "LLM not configured" },
      "risk-acknowledgement": { "status": "available" },
      "weather-adapter": { "status": "available" }
    },
    "api_version": "1.0.0",
    "server_time": "2026-09-04T10:00:00+08:00"
  }
}
```

## 4. 成员接口

### 4.1 创建成员

```
POST /households/{household_id}/members
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "display_name": "爷爷",
  "birth_date": "1945-03-15",
  "gender": "male",
  "relationship": "祖父",
  "notes": "高血压，每日服药"
}
```

**响应 201：**
```json
{
  "data": {
    "member_id": "m_001",
    "household_id": "h_001",
    "display_name": "爷爷",
    "birth_date": "1945-03-15",
    "gender": "male",
    "relationship": "祖父",
    "created_at": "2026-09-04T10:00:00+08:00"
  }
}
```

### 4.2 获取成员列表

```
GET /households/{household_id}/members
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "members": [
      {
        "member_id": "m_001",
        "display_name": "爷爷",
        "relationship": "祖父",
        "is_primary": true,
        "authorized_fields": ["medications", "allergies", "vitals"]
      }
    ]
  }
}
```

### 4.3 获取成员详情

```
GET /households/{household_id}/members/{member_id}
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "member_id": "m_001",
    "display_name": "爷爷",
    "birth_date": "1945-03-15",
    "gender": "male",
    "relationship": "祖父",
    "notes": "高血压，每日服药",
    "medications": [...],
    "allergies": [...],
    "conditions": [...],
    "latest_vitals": {...},
    "authorized_fields": ["medications", "allergies", "vitals"],
    "last_event_id": "e_001",
    "last_sequence_no": 42,
    "projection_checksum": "sha256:abc123..."
  }
}
```

未授权字段返回 `null` 或不包含在响应中。

### 4.4 更新成员

```
PATCH /households/{household_id}/members/{member_id}
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "display_name": "爷爷（张建国）",
  "notes": "高血压、糖尿病"
}
```

### 4.5 重放成员投影

```
POST /households/{household_id}/members/{member_id}/replay
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "from_checkpoint": "snap_001",
  "force": false
}
```

**响应 200：**
```json
{
  "data": {
    "member_id": "m_001",
    "replayed_events": 15,
    "last_sequence_no": 42,
    "new_checksum": "sha256:def456..."
  }
}
```

## 5. 健康事件接口

### 5.1 创建事件

```
POST /households/{household_id}/members/{member_id}/events
Authorization: Bearer <token>
Idempotency-Key: <unique-key>
```

**请求体：**
```json
{
  "event_type": "medication_added",
  "occurred_at": "2026-09-04T08:00:00+08:00",
  "source_type": "manual",
  "payload": {
    "medication": {
      "name": "氨氯地平",
      "dosage": "5mg",
      "frequency": "每日一次",
      "ingredients": [{"name": "氨氯地平", "amount": "5mg"}]
    }
  },
  "evidence_ids": ["ev_001"],
  "correlation_id": "corr_001"
}
```

**响应 201：**
```json
{
  "data": {
    "event_id": "e_001",
    "household_id": "h_001",
    "member_id": "m_001",
    "sequence_no": 43,
    "event_type": "medication_added",
    "occurred_at": "2026-09-04T08:00:00+08:00",
    "recorded_at": "2026-09-04T10:00:00+08:00",
    "actor_user_id": "u_001",
    "source_type": "manual",
    "payload": {...},
    "idempotency_key": "unique-key",
    "schema_version": 1
  }
}
```

### 5.2 获取事件列表

```
GET /households/{household_id}/members/{member_id}/events?cursor=xxx&limit=20&event_type=medication_added
Authorization: Bearer <token>
```

**查询参数：**
- `cursor`：分页游标
- `limit`：每页数量，默认 20，最大 100
- `event_type`：按事件类型过滤
- `from`：起始时间
- `to`：结束时间

**响应 200：**
```json
{
  "data": {
    "items": [...],
    "next_cursor": "eyJzZXF1ZW5jZV9ubyI6IDQzfQ==",
    "has_more": true
  }
}
```

### 5.3 获取事件详情

```
GET /households/{household_id}/members/{member_id}/events/{event_id}
Authorization: Bearer <token>
```

### 5.4 补偿事件

```
POST /households/{household_id}/members/{member_id}/events/{event_id}/compensate
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "reason": "药品名称录入错误",
  "correction_payload": {
    "medication": { "name": "氨氯地平片" }
  }
}
```

## 6. 药品接口

### 6.1 添加药品

```
POST /households/{household_id}/members/{member_id}/medications
Authorization: Bearer <token>
Idempotency-Key: <key>
```

**请求体：**
```json
{
  "name": "氨氯地平",
  "generic_name": "苯磺酸氨氯地平",
  "dosage": "5mg",
  "frequency": "每日一次",
  "manufacturer": "辉瑞制药",
  "batch_no": "B20260101",
  "expiry_date": "2027-12-31",
  "start_date": "2026-09-01",
  "ingredients": [
    {"name": "氨氯地平", "amount": "5mg"}
  ]
}
```

### 6.2 获取药品列表

```
GET /households/{household_id}/members/{member_id}/medications
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "medications": [
      {
        "medicine_id": "med_001",
        "name": "氨氯地平",
        "dosage": "5mg",
        "frequency": "每日一次",
        "status": "active",
        "expiry_date": "2027-12-31",
        "added_at": "2026-09-01T10:00:00+08:00"
      }
    ]
  }
}
```

### 6.3 更新药品

```
PATCH /households/{household_id}/members/{member_id}/medications/{medicine_id}
Authorization: Bearer <token>
```

### 6.4 移除药品

```
DELETE /households/{household_id}/members/{member_id}/medications/{medicine_id}
Authorization: Bearer <token>
```

移除是软删除，生成 `medication_removed` 事件。

## 7. 过敏与疾病接口

### 7.1 添加过敏

```
POST /households/{household_id}/members/{member_id}/allergies
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "substance": "青霉素",
  "category": "drug",
  "severity": "severe"
}
```

### 7.2 获取过敏列表

```
GET /households/{household_id}/members/{member_id}/allergies
Authorization: Bearer <token>
```

### 7.3 移除过敏

```
DELETE /households/{household_id}/members/{member_id}/allergies/{allergy_id}
Authorization: Bearer <token>
```

### 7.4 添加疾病

```
POST /households/{household_id}/members/{member_id}/conditions
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "name": "高血压",
  "category": "cardiovascular",
  "diagnosed_at": "2020-01-15"
}
```

## 8. 生命体征接口

### 8.1 记录体征

```
POST /households/{household_id}/members/{member_id}/vitals
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "type": "blood_pressure",
  "value": {"systolic": 145, "diastolic": 92},
  "unit": "mmHg",
  "measured_at": "2026-09-04T08:00:00+08:00"
}
```

### 8.2 获取体征历史

```
GET /households/{household_id}/members/{member_id}/vitals?type=blood_pressure&from=2026-08-01&to=2026-09-04
Authorization: Bearer <token>
```

### 8.3 获取最新体征

```
GET /households/{household_id}/members/{member_id}/vitals/latest
Authorization: Bearer <token>
```

## 9. 照护计划接口

### 9.1 创建服药计划

```
POST /households/{household_id}/members/{member_id}/plans
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "medicine_id": "med_001",
  "medicine_name": "氨氯地平",
  "dosage": "5mg",
  "frequency": "每日一次",
  "scheduled_times": ["08:00"],
  "start_date": "2026-09-01",
  "end_date": null
}
```

### 9.2 获取今日任务

```
GET /households/{household_id}/members/{member_id}/tasks/today
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "date": "2026-09-04",
    "tasks": [
      {
        "task_id": "task_001",
        "plan_id": "plan_001",
        "type": "medication",
        "title": "氨氯地平",
        "subtitle": "5mg",
        "scheduled_time": "08:00",
        "status": "pending",
        "allowed_actions": ["confirm", "defer", "skip", "missed"],
        "action_policy": {
          "require_reason": ["defer", "skip", "missed"],
          "max_defer_minutes": 120,
          "missed_grace_minutes": 60
        }
      }
    ],
    "summary": {
      "total": 3,
      "confirmed": 1,
      "pending": 2,
      "missed": 0
    }
  }
}
```

### 9.3 执行任务操作

```
POST /households/{household_id}/members/{member_id}/tasks/{task_id}/action
Authorization: Bearer <token>
Idempotency-Key: <key>
```

**请求体：**
```json
{
  "action": "confirm",
  "confirmed_at": "2026-09-04T08:05:00+08:00"
}
```

延期/跳过/记漏服需要原因：
```json
{
  "action": "defer",
  "reason": "正在吃饭，饭后再吃",
  "defer_minutes": 30
}
```

**响应 200：**
```json
{
  "data": {
    "event_id": "e_002",
    "task_id": "task_001",
    "status": "confirmed",
    "message": "已确认"
  }
}
```

### 9.4 获取任务操作历史

```
GET /households/{household_id}/members/{member_id}/tasks/{task_id}/history
Authorization: Bearer <token>
```

## 10. 风险提醒接口

### 10.1 获取风险列表

```
GET /households/{household_id}/risks?member_id=m_001&level=SEVERE,HIGH&status=active
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "items": [
      {
        "risk_id": "r_001",
        "member_id": "m_001",
        "risk_level": "SEVERE",
        "rule_id": "allergy_conflict",
        "rule_version": "1.2.0",
        "title": "青霉素过敏冲突",
        "description": "当前用药阿莫西林含有青霉素成分，与患者青霉素过敏冲突",
        "evidence": [
          {
            "evidence_id": "ev_001",
            "type": "allergy",
            "title": "青霉素过敏（严重）",
            "occurred_at": "2026-09-01T10:00:00+08:00"
          }
        ],
        "budget_status": "VISIBLE",
        "acknowledged": false,
        "created_at": "2026-09-04T09:00:00+08:00"
      }
    ],
    "next_cursor": null,
    "has_more": false
  }
}
```

### 10.2 获取风险详情

```
GET /households/{household_id}/risks/{risk_id}
Authorization: Bearer <token>
```

### 10.3 确认已知晓

```
POST /households/{household_id}/risks/{risk_id}/acknowledge
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "rule_version": "1.2.0",
  "risk_fingerprint": "sha256:abc123...",
  "note": "已咨询医生，暂停阿莫西林"
}
```

## 11. 视觉识别接口

### 11.1 上传文件

```
POST /files/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

**请求：**
- `file`：图片或视频文件
- 允许类型：image/jpeg, image/png, image/webp, video/mp4
- 最大大小：图片 10MB，视频 50MB

**响应 201：**
```json
{
  "data": {
    "file_reference": "file_001",
    "content_type": "image/jpeg",
    "size_bytes": 2048000,
    "uploaded_at": "2026-09-04T10:00:00+08:00"
  }
}
```

### 11.2 创建视觉任务

```
POST /households/{household_id}/vision-tasks
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "member_id": "m_001",
  "file_reference": "file_001",
  "media_type": "image",
  "source": "mobile_camera"
}
```

**响应 201：**
```json
{
  "data": {
    "task_id": "vt_001",
    "household_id": "h_001",
    "member_id": "m_001",
    "status": "QUEUED",
    "version": 1,
    "estimated_seconds": 15,
    "created_at": "2026-09-04T10:00:00+08:00"
  }
}
```

### 11.3 获取视觉任务状态

```
GET /households/{household_id}/vision-tasks/{task_id}
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "task_id": "vt_001",
    "status": "MATCHED",
    "version": 3,
    "candidates": [
      {
        "candidate_id": "cand_001",
        "medicine_name": "氨氯地平片",
        "specification": "5mg x 7片",
        "manufacturer": "辉瑞制药",
        "match_score": 0.95,
        "evidence": {
          "ocr_text": "氨氯地平片 5mg",
          "barcode": "6901234567890",
          "model_version": "vision-v2.1"
        },
        "source": "fusion"
      }
    ],
    "created_at": "2026-09-04T10:00:00+08:00",
    "updated_at": "2026-09-04T10:00:12+08:00"
  }
}
```

### 11.4 取消视觉任务

```
POST /households/{household_id}/vision-tasks/{task_id}/cancel
Authorization: Bearer <token>
If-Match: <version>
```

只有 QUEUED/PREPROCESSING/INFERENCING 状态可以取消。

### 11.5 确认识别结果

```
POST /households/{household_id}/vision-tasks/{task_id}/confirm
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "candidate_id": "cand_001"
}
```

确认后自动生成 `vision_confirmed` 事件和 `medication_added` 事件。

### 11.6 修正识别结果

```
POST /households/{household_id}/vision-tasks/{task_id}/correct
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "candidate_id": "cand_002",
  "correction": {
    "name": "氨氯地平片",
    "dosage": "5mg"
  },
  "reason": "OCR识别的规格有误"
}
```

## 12. 知识检索接口

### 12.1 获取知识文档列表

```
GET /knowledge/documents?category=medication&status=approved
Authorization: Bearer <token>
```

### 12.2 获取知识文档详情

```
GET /knowledge/documents/{document_id}
Authorization: Bearer <token>
```

### 12.3 知识检索

```
POST /knowledge/search
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "query": "高血压用药注意事项",
  "top_k": 5,
  "member_id": "m_001"
}
```

**响应 200：**
```json
{
  "data": {
    "results": [
      {
        "document_id": "doc_001",
        "chunk_id": "chunk_001",
        "title": "高血压用药指南",
        "score": 0.89,
        "snippet": "高血压患者应坚持规律服药...",
        "index_version": "2026.09"
      }
    ],
    "degraded": null
  }
}
```

无授权文档时返回降级：
```json
{
  "data": {
    "results": [],
    "degraded": {
      "code": "NO_AUTHORISED_DOCUMENTS",
      "message": "当前没有已授权的知识文档"
    }
  }
}
```

## 13. 助手对话接口

### 13.1 发送消息

```
POST /assistant/chat
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "household_id": "h_001",
  "member_id": "m_001",
  "message": "爷爷今天的血压有点高，应该注意什么？",
  "conversation_id": "conv_001",
  "allow_external_web": false
}
```

**响应 200：**
```json
{
  "data": {
    "reply_id": "reply_001",
    "route": "knowledge_qa",
    "content": "根据爷爷的血压记录（145/92），建议...",
    "citations": [
      {
        "document_id": "doc_001",
        "chunk_id": "chunk_001",
        "version": "2026.09",
        "title": "高血压用药指南"
      }
    ],
    "tool_calls": [
      {
        "tool": "knowledge_search",
        "status": "success",
        "result_count": 3,
        "duration_ms": 450
      }
    ],
    "evidence_complete": true,
    "model_version": "llm-local-v1",
    "created_at": "2026-09-04T10:00:00+08:00"
  }
}
```

### 13.2 流式对话

```
POST /assistant/chat/stream
Authorization: Bearer <token>
Accept: text/event-stream
```

**SSE 事件流：**
```
event: agent_stage
data: {"stage": "thinking", "message": "正在分析问题..."}

event: evidence_preview
data: {"type": "knowledge", "preview": "高血压用药指南..."}

event: content_delta
data: {"delta": "根据"}

event: content_delta
data: {"delta": "爷爷的"}

event: tool_call
data: {"tool": "knowledge_search", "status": "success", "result_count": 3}

event: done
data: {"reply_id": "reply_001", "citations": [...], "model_version": "llm-local-v1"}
```

### 13.3 停止生成

```
POST /assistant/chat/{reply_id}/stop
Authorization: Bearer <token>
```

## 14. 授权接口

### 14.1 创建授权

```
POST /households/{household_id}/authorizations
Authorization: Bearer <token>
```

**请求体：**
```json
{
  "grantee_user_id": "u_002",
  "member_id": "m_001",
  "data_fields": ["medications", "allergies", "vitals"],
  "actions": ["read"],
  "purpose": "family_care",
  "valid_from": "2026-09-04T10:00:00+08:00",
  "valid_until": "2027-09-04T10:00:00+08:00"
}
```

### 14.2 获取授权列表

```
GET /households/{household_id}/authorizations
Authorization: Bearer <token>
```

### 14.3 更新授权

```
PATCH /households/{household_id}/authorizations/{authorization_id}
Authorization: Bearer <token>
If-Match: <version>
```

### 14.4 撤销授权

```
POST /households/{household_id}/authorizations/{authorization_id}/revoke
Authorization: Bearer <token>
If-Match: <version>
```

**请求体：**
```json
{
  "reason": "不再需要照护",
  "expected_version": 2
}
```

### 14.5 获取授权审计日志

```
GET /households/{household_id}/authorizations/{authorization_id}/audits
Authorization: Bearer <token>
```

## 15. 环境行动卡接口

### 15.1 获取天气和行动卡

```
GET /households/{household_id}/environment/action-cards?city_code=130300&member_id=m_001
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "weather": {
      "city_code": "130300",
      "city_name": "秦皇岛",
      "condition": "晴",
      "temperature_high": 28,
      "temperature_low": 18,
      "humidity": 65,
      "aqi": 45,
      "aqi_level": "优",
      "uv_index": 6,
      "data_source": "mock",
      "updated_at": "2026-09-04T10:00:00+08:00"
    },
    "action_cards": [
      {
        "card_id": "card_001",
        "type": "uv_protection",
        "title": "紫外线较强，注意防晒",
        "content": "今日紫外线指数 6，建议外出时...",
        "severity": "INFO",
        "related_member_ids": ["m_001"],
        "valid_until": "2026-09-04T18:00:00+08:00"
      }
    ],
    "disclaimer": "天气数据仅供参考，行动建议不构成医疗建议"
  }
}
```

## 16. 健康资讯接口

### 16.1 获取健康资讯

```
GET /health-news?category=medication&limit=10
Authorization: Bearer <token>
```

**响应 200：**
```json
{
  "data": {
    "items": [
      {
        "news_id": "news_001",
        "title": "秋季高血压管理要点",
        "category": "cardiovascular",
        "summary": "秋季气温变化大，高血压患者应注意...",
        "source": "家庭健康知识库",
        "published_at": "2026-09-01T10:00:00+08:00",
        "freshness": "fresh"
      }
    ],
    "last_updated": "2026-09-04T10:00:00+08:00",
    "ttl_seconds": 3600
  }
}
```

## 17. 文件与诊断接口

### 17.1 客户端日志上报

```
POST /client-logs
Authorization: Bearer <token>
```

### 17.2 客户端错误上报

```
POST /client-errors
Authorization: Bearer <token>
```

### 17.3 性能指标上报

```
POST /client-metrics
Authorization: Bearer <token>
```

---

*API 文档随版本迭代更新。实际接口以 `/docs`（Swagger UI）和 `/openapi.json` 为准。*
