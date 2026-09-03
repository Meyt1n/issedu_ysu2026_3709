# 移动端 API 对接手册

> 本文档是家健镜随身版与 FastAPI 后端对接的完整参考，覆盖认证、家庭与成员、健康事件、风险与计划、视觉识别、知识检索、助手对话、能力探测等全部接口。面向后端和移动端开发者，作为联调、测试和问题排查的权威依据。

## 1. 基础约定

### 1.1 服务地址

| 环境 | 地址 | 说明 |
| --- | --- | --- |
| 本地开发 | `http://127.0.0.1:8000` | 后端本地进程 |
| 联调环境 | `http://<局域网IP>:18800` | 移动端联调专用端口，SQLite |
| Docker Compose | `http://localhost:8000` | Nginx 反代或直接暴露 |
| 生产部署 | `https://<家庭服务器域名>` | HTTPS，家庭局域网内 |

移动端在「我的 → 数据来源」中配置服务器地址，支持 HTTP（家庭局域网）和 HTTPS。Release APK 仅允许 HTTPS；Debug APK 允许家庭局域网 HTTP，但拒绝公网 HTTP。

### 1.2 API 版本

所有接口前缀为 `/api/v1`。版本升级时新增 `/api/v2`，旧版本保留至少一个发布周期。

### 1.3 数据格式

- 请求和响应均为 `application/json`
- 字段命名使用 `snake_case`
- 时间使用 ISO 8601 含时区格式：`2026-09-03T14:30:00+08:00`
- 布尔值为 `true` / `false`
- 空值为 `null`，不使用空字符串代替 null
- 列表分页使用游标分页（`cursor` + `limit`），不使用 offset

### 1.4 请求头

| 头 | 必填 | 说明 |
| --- | --- | --- |
| `Content-Type` | 是 | `application/json` |
| `Authorization` | 登录后必填 | `Bearer <session_token>` |
| `X-Access-Purpose` | 非 Owner 必填 | ASCII 目的代码，如 `care_daily_check`、`medication_reminder` |
| `Idempotency-Key` | 写操作推荐 | 最长 128 字符，服务端按家庭+键去重 |
| `X-Request-ID` | 否 | 客户端生成的追踪 ID，服务端回显 |

### 1.5 响应格式

成功响应直接返回数据对象或列表：

```json
{
  "id": "evt_abc123",
  "household_id": "hh_001",
  "member_id": "mem_001",
  "event_type": "medication_added",
  "occurred_at": "2026-09-03T14:30:00+08:00"
}
```

列表响应：

```json
{
  "items": [...],
  "next_cursor": "eyJzZXF1ZW5jZV9ubyI6IDEwfQ==",
  "has_more": true
}
```

### 1.6 错误格式

P0 使用 FastAPI 默认错误格式：

```json
{
  "detail": "事件不存在或无权限访问"
}
```

P1 统一为结构化错误：

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "事件不存在或无权限访问",
    "request_id": "req_abc123",
    "details": {}
  }
}
```

### 1.7 错误码表

| HTTP | code | 说明 | 客户端处理 |
| --- | --- | --- | --- |
| 400 | `VALIDATION_ERROR` | 请求参数校验失败 | 显示字段级错误 |
| 401 | `UNAUTHORIZED` | 未登录或会话过期 | 清除会话，跳转登录 |
| 403 | `ACCESS_DENIED` | 无权限访问 | 显示无权限提示 |
| 404 | `RESOURCE_NOT_FOUND` | 资源不存在 | 显示不存在（不区分无权限） |
| 409 | `IDEMPOTENCY_KEY_CONFLICT` | 幂等键冲突 | 提示操作已提交 |
| 409 | `AUTHORIZATION_VERSION_CONFLICT` | 授权版本冲突 | 重新加载授权 |
| 409 | `PROJECTION_CHECKSUM_MISMATCH` | 投影校验和不匹配 | 触发重放 |
| 422 | `VALIDATION_ERROR` | Pydantic 校验失败 | 显示字段错误 |
| 429 | `RATE_LIMITED` | 限流 | 禁用重试，显示提示 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 | 显示错误，提供重试 |
| 503 | `SERVICE_UNAVAILABLE` | 服务不可用 | 保留旧数据，提示稍后重试 |

## 2. 认证接口

### 2.1 注册

`POST /api/v1/auth/register`

**请求体：**

```json
{
  "username": "zhangsan",
  "password": "MyPass123",
  "display_name": "张三"
}
```

**约束：**
- 用户名：3-32 字符，字母数字下划线
- 密码：≥8 位，同时含字母和数字
- display_name：1-50 字符

**响应 201：**

```json
{
  "user_id": "usr_abc123",
  "username": "zhangsan",
  "display_name": "张三",
  "created_at": "2026-09-03T14:30:00+08:00"
}
```

**错误：**
- 409 `USERNAME_TAKEN`：用户名已存在

### 2.2 登录

`POST /api/v1/auth/login`

**请求体：**

```json
{
  "username": "zhangsan",
  "password": "MyPass123"
}
```

**响应 200：**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "user_id": "usr_abc123",
    "username": "zhangsan",
    "display_name": "张三"
  }
}
```

**安全说明：**
- `access_token` 是短期会话令牌，客户端仅存内存
- 不提供 refresh_token，过期后重新登录
- 连续失败 5 次锁定 15 分钟

### 2.3 修改密码

`POST /api/v1/auth/change-password`

**请求头：** `Authorization: Bearer <token>`

**请求体：**

```json
{
  "old_password": "MyPass123",
  "new_password": "NewPass456"
}
```

**响应 200：**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "message": "密码已修改，所有其他设备已登出"
}
```

**行为：**
- 服务端验证旧密码后，撤销该用户全部旧会话
- 签发新会话，当前设备保持登录
- 客户端立即采纳新 token，清除密码输入框

**错误：**
- 401 `INVALID_CREDENTIALS`：旧密码错误
- 400 `PASSWORD_TOO_WEAK`：新密码不符合策略
- 400 `PASSWORD_SAME_AS_OLD`：新密码与旧密码相同

### 2.4 登出

`POST /api/v1/auth/logout`

**请求头：** `Authorization: Bearer <token>`

**响应 204：** 无内容

**行为：** 撤销当前会话，客户端清除内存 token。

### 2.5 会话续验

`POST /api/v1/auth/session`

**请求头：** `Authorization: Bearer <token>`

**响应 200：**

```json
{
  "user_id": "usr_abc123",
  "username": "zhangsan",
  "display_name": "张三",
  "expires_at": "2026-09-03T15:30:00+08:00"
}
```

**用途：** 应用启动时验证会话是否仍有效，避免静默过期。

## 3. 家庭与成员接口

### 3.1 创建家庭

`POST /api/v1/households`

**请求体：**

```json
{
  "name": "张家",
  "timezone": "Asia/Shanghai"
}
```

**响应 201：**

```json
{
  "household_id": "hh_001",
  "name": "张家",
  "timezone": "Asia/Shanghai",
  "created_by": "usr_abc123",
  "role": "owner",
  "created_at": "2026-09-03T14:30:00+08:00"
}
```

**说明：** 创建者自动成为家庭 Owner，拥有完整访问权限。

### 3.2 列出家庭

`GET /api/v1/households`

**响应 200：**

```json
{
  "items": [
    {
      "household_id": "hh_001",
      "name": "张家",
      "timezone": "Asia/Shanghai",
      "role": "owner",
      "member_count": 3
    }
  ]
}
```

### 3.3 修改家庭

`PATCH /api/v1/households/{household_id}`

**权限：** 仅 Owner

**请求体（可选字段）：**

```json
{
  "name": "张家（更新）",
  "timezone": "Asia/Shanghai"
}
```

### 3.4 添加成员

`POST /api/v1/households/{household_id}/members`

**请求体：**

```json
{
  "display_name": "张爷爷",
  "birth_date": "1945-03-15",
  "gender": "male",
  "relationship": "grandfather",
  "notes": "高血压，每日服药"
}
```

**响应 201：**

```json
{
  "member_id": "mem_001",
  "household_id": "hh_001",
  "display_name": "张爷爷",
  "birth_date": "1945-03-15",
  "gender": "male",
  "relationship": "grandfather",
  "created_at": "2026-09-03T14:30:00+08:00"
}
```

### 3.5 列出成员

`GET /api/v1/households/{household_id}/members`

**响应 200：**

```json
{
  "items": [
    {
      "member_id": "mem_001",
      "display_name": "张爷爷",
      "relationship": "grandfather",
      "authorized_fields": ["medications", "vitals", "risks"],
      "is_primary": true
    }
  ]
}
```

**授权过滤：** 非 Owner 只能看到被授权的成员，且字段按授权范围过滤。

## 4. 授权接口

### 4.1 创建授权

`POST /api/v1/households/{household_id}/authorizations`

**权限：** 仅 Owner

**请求体：**

```json
{
  "grantee_user_id": "usr_caregiver1",
  "member_id": "mem_001",
  "data_fields": ["medications", "vitals", "risks", "events"],
  "actions": ["read", "confirm_task", "acknowledge_risk"],
  "purpose": "care_daily_check",
  "valid_from": "2026-09-03T00:00:00+08:00",
  "valid_until": "2026-12-31T23:59:59+08:00"
}
```

**响应 201：**

```json
{
  "authorization_id": "auth_001",
  "version": 1,
  "status": "active",
  "created_at": "2026-09-03T14:30:00+08:00"
}
```

### 4.2 查询授权

`GET /api/v1/households/{household_id}/authorizations`

**查询参数：**
- `member_id`：按成员过滤
- `grantee_user_id`：按被授权人过滤
- `status`：`active` / `revoked` / `expired`

### 4.3 修改授权

`PATCH /api/v1/households/{household_id}/authorizations/{authorization_id}`

**权限：** 仅 Owner

**请求体：**

```json
{
  "data_fields": ["medications", "vitals"],
  "actions": ["read"],
  "valid_until": "2026-10-31T23:59:59+08:00",
  "expected_version": 1
}
```

**并发控制：** 使用 `expected_version` 乐观锁，冲突返回 409 `AUTHORIZATION_VERSION_CONFLICT`。

### 4.4 撤销授权

`POST /api/v1/households/{household_id}/authorizations/{authorization_id}/revoke`

**权限：** 仅 Owner

**请求体：**

```json
{
  "reason": "照护关系结束",
  "expected_version": 2
}
```

### 4.5 授权审计

`GET /api/v1/households/{household_id}/authorization-audits`

**权限：** 仅 Owner

**响应：** 授权生命周期和非 Owner 访问决定的最小元数据，不包含健康正文。

## 5. 健康事件接口

### 5.1 追加事件

`POST /api/v1/households/{household_id}/events`

**请求头：** `Idempotency-Key: medication_add_aspirin_001`

**请求体：**

```json
{
  "member_id": "mem_001",
  "event_type": "medication_added",
  "occurred_at": "2026-09-03T14:30:00+08:00",
  "source_type": "manual",
  "payload": {
    "medicine_name": "阿司匹林肠溶片",
    "dosage": "100mg",
    "frequency": "每日一次",
    "start_date": "2026-09-03"
  },
  "evidence_ids": [],
  "correlation_id": "corr_001"
}
```

**响应 201：**

```json
{
  "event_id": "evt_001",
  "sequence_no": 15,
  "member_id": "mem_001",
  "event_type": "medication_added",
  "occurred_at": "2026-09-03T14:30:00+08:00",
  "recorded_at": "2026-09-03T14:30:01+08:00",
  "actor_user_id": "usr_abc123",
  "source_type": "manual",
  "idempotency_key": "medication_add_aspirin_001",
  "schema_version": 1
}
```

**幂等行为：**
- 相同 `Idempotency-Key` 重复提交，返回原事件（200）
- 相同键但 payload 不同，返回 409 `IDEMPOTENCY_KEY_CONFLICT`

### 5.2 查询事件

`GET /api/v1/households/{household_id}/events`

**查询参数：**
- `member_id`：按成员过滤
- `event_type`：按类型过滤
- `source_type`：按来源过滤
- `from` / `to`：时间范围
- `cursor`：分页游标
- `limit`：每页数量（默认 20，最大 100）

**响应 200：**

```json
{
  "items": [
    {
      "event_id": "evt_001",
      "sequence_no": 15,
      "member_id": "mem_001",
      "event_type": "medication_added",
      "occurred_at": "2026-09-03T14:30:00+08:00",
      "source_type": "manual",
      "summary": "添加药品：阿司匹林肠溶片 100mg",
      "actor_display_name": "张三"
    }
  ],
  "next_cursor": "eyJzZXF1ZW5jZV9ubyI6IDE1fQ==",
  "has_more": true
}
```

**授权过滤：** 非 Owner 只能看到被授权成员的事件，且敏感字段按授权范围脱敏。

### 5.3 游标分页查询

`GET /api/v1/households/{household_id}/events/page`

与 5.2 相同，但强制使用游标分页，适合移动端无限滚动。

### 5.4 追加补偿事件

`POST /api/v1/households/{household_id}/events/{event_id}/compensations`

**用途：** 更正已确认的事件，原事件不可修改，只能追加补偿事件。

**请求体：**

```json
{
  "reason": "药品名称录入错误，应为阿司匹林不是阿莫西林",
  "correction_payload": {
    "medicine_name": "阿司匹林肠溶片"
  }
}
```

**约束：**
- 只能引用本家庭、本成员的已确认事件
- 补偿事件携带 `supersedes_event_id` 指向原事件
- 原事件状态标记为 `superseded`，但数据保留

### 5.5 查询成员状态投影

`GET /api/v1/households/{household_id}/members/{member_id}/state`

**响应 200：**

```json
{
  "member_id": "mem_001",
  "last_event_id": "evt_015",
  "last_sequence_no": 15,
  "projection_version": "v1.2.3",
  "projection_checksum": "sha256:abc123...",
  "state": {
    "medications": [
      {
        "medicine_id": "med_001",
        "name": "阿司匹林肠溶片",
        "dosage": "100mg",
        "frequency": "每日一次",
        "start_date": "2026-09-03",
        "status": "active"
      }
    ],
    "allergies": ["青霉素"],
    "conditions": ["高血压"],
    "latest_vitals": {
      "blood_pressure": {"systolic": 145, "diastolic": 90, "measured_at": "2026-09-02T08:00:00+08:00"}
    }
  }
}
```

**说明：** 状态投影由事件重放生成，每个字段可追溯到确认事件。`UNCONFIRMED` 事件不更新投影。

### 5.6 重放状态投影

`POST /api/v1/households/{household_id}/members/{member_id}/state/replay`

**权限：** 仅 Owner

**请求体（可选）：**

```json
{
  "from_checkpoint": "chk_001",
  "force": false
}
```

**行为：** 从空状态或指定 checkpoint 开始重放全部事件，重建投影。checkpoint 哈希不匹配返回 409。

## 6. Outbox 接口

### 6.1 查询 outbox 状态

`GET /api/v1/households/{household_id}/outbox`

**查询参数：**
- `status`：`PENDING` / `PROCESSING` / `FAILED` / `DISPATCHED`
- `member_id`：按成员过滤

**响应：** outbox 消息列表，含事件引用、状态、尝试次数、错误信息。

### 6.2 手动触发恢复

`POST /api/v1/households/{household_id}/outbox/recover`

**权限：** 仅 Owner

**行为：** 回收过期锁，重新派发 FAILED 消息。用于 outbox worker 异常后的手动恢复。

## 7. 风险接口

### 7.1 查询风险列表

`GET /api/v1/households/{household_id}/members/{member_id}/risks`

**查询参数：**
- `level`：`SEVERE` / `HIGH` / `INFO` / `LOW`
- `status`：`active` / `acknowledged` / `expired`
- `cursor` / `limit`

**响应 200：**

```json
{
  "items": [
    {
      "risk_id": "risk_001",
      "level": "SEVERE",
      "rule_id": "allergy_conflict",
      "rule_version": "v1.0.0",
      "title": "过敏风险：青霉素与阿莫西林",
      "description": "成员对青霉素过敏，当前用药含阿莫西林，存在交叉过敏风险",
      "budget_status": "VISIBLE",
      "merged_count": 1,
      "acknowledged": false,
      "created_at": "2026-09-03T10:00:00+08:00",
      "valid_until": "2026-09-04T10:00:00+08:00",
      "evidence_count": 2
    }
  ],
  "next_cursor": "...",
  "has_more": false
}
```

**预算说明：**
- `SEVERE`：不受预算压制，始终可见
- `HIGH`：合并但不静默
- `INFO` / `LOW`：受成员每日预算控制，超预算时 `budget_status=SUPPRESSED`

### 7.2 查询风险详情

`GET /api/v1/households/{household_id}/risks/{risk_id}`

**响应 200：** 含完整证据列表、参与事实、规则版本、推荐确认角色。

### 7.3 确认已知晓

`POST /api/v1/households/{household_id}/risks/{risk_id}/acknowledge`

**请求头：** `Idempotency-Key: ack_risk_001`

**请求体：**

```json
{
  "rule_version": "v1.0.0",
  "risk_fingerprint": "sha256:abc123...",
  "note": "已联系医生确认换药"
}
```

**行为：**
- 服务端重新计算规则版本和风险指纹，与客户端提交的比对
- 不一致则返回 409，客户端需重新加载风险
- 确认后风险状态为 `acknowledged`，不再出现在活跃列表

**能力门控：** 服务端未声明 `risk-acknowledgement` 能力时，此接口返回 503，客户端按钮置灰。

## 8. 照护计划接口

### 8.1 查询今日任务

`GET /api/v1/households/{household_id}/members/{member_id}/tasks/today`

**响应 200：**

```json
{
  "date": "2026-09-03",
  "tasks": [
    {
      "task_id": "task_001",
      "plan_id": "plan_001",
      "type": "medication",
      "title": "阿司匹林肠溶片",
      "subtitle": "100mg · 早餐后",
      "scheduled_time": "08:00",
      "status": "pending",
      "allowed_actions": ["confirm", "defer", "skip", "missed"],
      "action_policy": {
        "require_reason": ["defer", "skip", "missed"],
        "max_defer_minutes": 120,
        "missed_grace_minutes": 30
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
```

**动作边界：** `allowed_actions` 由服务端决定，客户端不推断安全窗口。服务端未返回时按钮置灰。

### 8.2 计划工作台

`GET /api/v1/households/{household_id}/members/{member_id}/plan-workbench`

**响应 200：** 含全部计划的动作策略、状态、下次动作时间。移动端今日页据此渲染任务卡。

### 8.3 确认任务

`POST /api/v1/households/{household_id}/plans/{plan_id}/confirm`

**请求头：** `Idempotency-Key: confirm_plan_001_20260903`

**请求体：**

```json
{
  "task_id": "task_001",
  "confirmed_at": "2026-09-03T08:15:00+08:00"
}
```

**响应 200：** 含事件 ID 和更新后的任务状态。

### 8.4 延期任务

`POST /api/v1/households/{household_id}/plans/{plan_id}/defer`

**请求体：**

```json
{
  "task_id": "task_001",
  "defer_minutes": 30,
  "reason": "正在吃饭，稍后服用"
}
```

### 8.5 跳过任务

`POST /api/v1/households/{household_id}/plans/{plan_id}/skip`

**请求体：**

```json
{
  "task_id": "task_001",
  "reason": "今日无需服用"
}
```

### 8.6 记漏服

`POST /api/v1/households/{household_id}/plans/{plan_id}/missed`

**请求体：**

```json
{
  "task_id": "task_001",
  "reason": "忘记服用"
}
```

**行为：** 只落一条漏服事实，不自动补服、不修改剂量或提醒时间。

### 8.7 查询任务操作历史

`GET /api/v1/households/{household_id}/members/{member_id}/task-history`

**响应：** 按计划展示动作事件的脱敏摘要（动作、任务、时间、事件回执、最终状态）。同一计划的重复动作只计一条有效回执，更早动作标注「已被覆盖」。

## 9. 视觉识别接口

### 9.1 创建视觉任务

`POST /api/v1/vision-tasks`

**请求体：**

```json
{
  "household_id": "hh_001",
  "member_id": "mem_001",
  "file_reference": "file_abc123",
  "media_type": "image",
  "source": "mobile_camera"
}
```

**响应 202：**

```json
{
  "task_id": "vt_001",
  "status": "QUEUED",
  "created_at": "2026-09-03T14:30:00+08:00",
  "estimated_seconds": 15
}
```

### 9.2 上传证据

`POST /api/v1/vision-tasks/{task_id}/evidence`

**用途：** 本地适配器签名的 OCR-first 证据上传。

### 9.3 融合候选

`POST /api/v1/vision-tasks/{task_id}/fusion`

**用途：** 融合批准主数据候选，创建唯一待复核任务。

### 9.4 查询任务状态

`GET /api/v1/vision-tasks/{task_id}`

**响应 200：**

```json
{
  "task_id": "vt_001",
  "status": "MATCHED",
  "version": 5,
  "created_at": "2026-09-03T14:30:00+08:00",
  "updated_at": "2026-09-03T14:30:12+08:00",
  "candidates": [
    {
      "candidate_id": "cand_001",
      "medicine_name": "阿司匹林肠溶片",
      "specification": "100mg×30片",
      "manufacturer": "拜耳",
      "match_score": 0.92,
      "evidence": {
        "ocr_text": "阿司匹林肠溶片 100mg",
        "barcode": "6901234567890",
        "package_type": "medicine_box"
      }
    }
  ],
  "review_task_id": "rt_001"
}
```

**状态机：**

```
QUEUED → PREPROCESSING → INFERENCING → FUSING
       → MATCHED | CONFLICT | UNKNOWN | REVIEW | FAILED
       → CANCELLED（任意非终态可取消）
```

### 9.5 取消视觉任务

`POST /api/v1/vision-tasks/{task_id}/cancel`

**行为：**
- 仅非终态任务可取消
- 复用同一 taskId，不重新上传、不新建任务
- 取消后任务进入 `CANCELLED` 终态
- 取消失败返回错误码和「重试回查」入口

### 9.6 重试视觉任务

`POST /api/v1/vision-tasks/{task_id}/retry`

**用途：** 失败/超时任务原地重新排队，不创建新任务。

### 9.7 查询待复核任务

`GET /api/v1/households/{household_id}/members/{member_id}/review-tasks`

**响应：** 有权限成员的待复核任务列表。

### 9.8 确认候选

`POST /api/v1/households/{household_id}/review-tasks/{review_task_id}/confirm`

**行为：** 确认候选并追加健康事件。移动端不直接调用此接口（候选确认在网页端复核中心完成）。

### 9.9 修正候选

`POST /api/v1/households/{household_id}/review-tasks/{review_task_id}/correct`

**行为：** 人工修正并追加健康事件，保存原预测、前后值、原因和操作者。

### 9.10 跳过复核

`POST /api/v1/households/{household_id}/review-tasks/{review_task_id}/skip`

**行为：** 跳过复核且不创建健康事件。

## 10. 知识检索接口

### 10.1 列出知识文档

`GET /api/v1/knowledge/documents`

**查询参数：**
- `status`：`approved` / `pending` / `rejected`
- `category`：按分类过滤
- `cursor` / `limit`

**响应 200：**

```json
{
  "items": [
    {
      "document_id": "doc_001",
      "title": "高血压用药基础",
      "category": "medication",
      "status": "approved",
      "source": "家庭健康手册",
      "license": "internal",
      "index_version": "idx-2026-09",
      "effective_at": "2026-09-01T00:00:00+08:00",
      "chunk_count": 5
    }
  ]
}
```

**过滤：** 移动端只展示已批准（`approved`）条目。

### 10.2 检索知识

`POST /api/v1/knowledge/retrieve`

**请求体：**

```json
{
  "query": "阿司匹林什么时间吃",
  "top_k": 5,
  "member_id": "mem_001"
}
```

**响应 200：**

```json
{
  "results": [
    {
      "document_id": "doc_001",
      "chunk_id": "chunk_003",
      "title": "高血压用药基础",
      "score": 0.85,
      "snippet": "阿司匹林建议早餐后服用，减少胃肠道刺激...",
      "index_version": "idx-2026-09"
    }
  ],
  "degraded": null
}
```

**降级响应：**

```json
{
  "results": [],
  "degraded": {
    "code": "NO_AUTHORISED_DOCUMENTS",
    "message": "当前成员无授权的知识文档"
  }
}
```

**降级码：**
- `NO_AUTHORISED_DOCUMENTS`：无授权文档
- `EMPTY_INDEX`：索引为空
- `NO_RELEVANT_RESULTS`：无相关结果
- `KNOWLEDGE_UNAVAILABLE`：服务不可用

**安全：** 检索词仅进请求体，不进 URL、不写本机存储。权限过滤和排序在服务端完成。

### 10.3 查询文档详情

`GET /api/v1/knowledge/documents/{document_id}`

**响应 200：** 含来源、许可、索引版本、生效时间、正文分块。

### 10.4 知识爬虫状态

`GET /api/v1/knowledge/crawl/status`

**权限：** 仅知识管理员。移动端不调用此接口。

## 11. 助手对话接口

### 11.1 普通对话

`POST /api/v1/assistant/chat`

**请求体：**

```json
{
  "household_id": "hh_001",
  "member_id": "mem_001",
  "message": "张爷爷今天的血压怎么样？",
  "allow_external_web": false,
  "conversation_id": "conv_001"
}
```

**响应 200：**

```json
{
  "reply_id": "reply_001",
  "route": "data_query",
  "content": "张爷爷最近一次血压测量是 2026-09-02 早上 8 点，收缩压 145，舒张压 90，属于偏高范围。建议按医嘱服药并定期监测。",
  "citations": [
    {
      "document_id": "doc_001",
      "chunk_id": "chunk_002",
      "version": "idx-2026-09",
      "quote": "血压收缩压≥140或舒张压≥90为高血压"
    }
  ],
  "tool_calls": [
    {"tool": "member_state_query", "status": "success"}
  ],
  "evidence_complete": true,
  "degraded": null,
  "model_version": "local-llm-v5",
  "created_at": "2026-09-03T14:30:00+08:00"
}
```

**约束：**
- 只执行白名单只读工具（SQL 查询、图谱查询、规则查询、RAG 检索）
- 不做诊断、处方、停药、换药、调剂量
- citations 只能引用本次工具返回的文档，伪造来源返回 `CITATION_NOT_FOUND`

### 11.2 流式对话

`POST /api/v1/assistant/chat/stream`

**请求体：** 同普通对话

**响应：** `text/event-stream`，逐块推送：

```
event: agent_stage
data: {"stage": "routing", "message": "正在理解问题..."}

event: evidence_preview
data: {"type": "member_state", "preview": "血压 145/90，2026-09-02"}

event: content_delta
data: {"delta": "张爷爷最近一次血压"}

event: content_delta
data: {"delta": "测量是 2026-09-02..."}

event: tool_call
data: {"tool": "rag_search", "status": "success", "result_count": 3}

event: done
data: {"reply_id": "reply_001", "citations": [...], "model_version": "local-llm-v5"}
```

**错误：** 流错误推送 `event: error`，客户端回退到普通对话接口。

### 11.3 停止生成

`POST /api/v1/assistant/chat/stop`

**请求体：**

```json
{
  "reply_id": "reply_001",
  "conversation_id": "conv_001"
}
```

**行为：** 服务端取消生成，返回已生成内容。客户端同时使用 `AbortController` 中断流。

### 11.4 查询可用助手

`GET /api/v1/assistant/agents`

**响应：** 可用助手代理与能力声明。

## 12. 能力探测接口

### 12.1 查询系统能力

`GET /api/v1/meta/capabilities`

**响应 200：**

```json
{
  "capabilities": {
    "manual-health-event": {"status": "available", "version": "v1"},
    "household-member": {"status": "available", "version": "v1"},
    "field-authorization": {"status": "available", "version": "v1"},
    "audit-outbox": {"status": "available", "version": "v1"},
    "review-task": {"status": "available", "version": "v1"},
    "vision-task": {"status": "available", "version": "v1"},
    "vision-inference": {"status": "unavailable", "reason": "vision_worker_not_configured"},
    "knowledge-store": {"status": "available", "version": "v1"},
    "local-assistant": {"status": "available", "version": "v1"},
    "risk-acknowledgement": {"status": "available", "version": "v1"},
    "plan-workbench": {"status": "available", "version": "v1"},
    "external-web": {"status": "unavailable", "reason": "disabled_by_default"},
    "face-recognition-local": {"status": "unavailable", "reason": "not_configured"},
    "llm": {"status": "unavailable", "reason": "ollama_not_running"},
    "weather-adapter": {"status": "available", "version": "v1"}
  },
  "api_version": "v1.2.0",
  "server_time": "2026-09-03T14:30:00+08:00"
}
```

**客户端行为：**
- 应用启动时调用一次，结果缓存到 runtime store
- 各功能模块根据能力声明决定 UI 行为
- 能力不可用时如实提示，不冒充可用
- `available` / `unavailable` 二态，无「可能」「大概」

### 12.2 健康检查

`GET /health`

**响应 200：** `{"status": "ok"}`

### 12.3 数据库健康检查

`GET /api/v1/health/db`

**响应 200：** 数据库连接状态。

## 13. 文件上传接口

### 13.1 上传文件

`POST /api/v1/files/upload`

**Content-Type:** `multipart/form-data`

**字段：**
- `file`：文件内容
- `household_id`：家庭 ID
- `purpose`：`vision_evidence` / `profile_photo` / `document`

**约束：**
- MIME 白名单：image/jpeg, image/png, image/webp, video/mp4, application/pdf
- 图片大小 ≤10MiB，视频 ≤10MiB 且 ≤30s
- 服务端执行内容探测，不依赖客户端声明的 MIME

**响应 201：**

```json
{
  "file_reference": "file_abc123",
  "content_type": "image/jpeg",
  "size_bytes": 1048576,
  "uploaded_at": "2026-09-03T14:30:00+08:00"
}
```

**安全：** 文件存储在家庭本地，不出网。文件名随机化，不保留原始文件名。

## 14. 健康资讯接口

### 14.1 获取健康资讯

`GET /api/v1/health-news`

**查询参数：**
- `category`：`medication` / `nutrition` / `exercise` / `seasonal`
- `limit`：数量（默认 5）

**响应 200：**

```json
{
  "items": [
    {
      "news_id": "news_001",
      "title": "秋季高血压管理要点",
      "category": "seasonal",
      "summary": "秋季气温变化大，高血压患者需注意...",
      "source": "local_health_digest",
      "published_at": "2026-09-01T00:00:00+08:00",
      "freshness": "fresh"
    }
  ],
  "last_updated": "2026-09-03T08:00:00+08:00",
  "ttl_seconds": 86400
}
```

**新鲜度四态：** `fresh` / `stale` / `expired` / `unknown`

**客户端缓存：** 按 `ttl_seconds` 缓存，过期显示 `role=alert` 提示并提供「一键刷新」。

## 15. 环境行动卡接口

### 15.1 获取环境行动卡

`GET /api/v1/environment/action-cards`

**查询参数：**
- `household_id`
- `member_id`
- `city_code`：6 位行政区划代码（如 `130600` 保定）

**响应 200：**

```json
{
  "city_code": "130600",
  "city_name": "保定市",
  "weather": {
    "condition": "晴",
    "temperature_high": 28,
    "temperature_low": 18,
    "humidity": 45,
    "aqi": 72,
    "aqi_level": "良",
    "uv_index": 6,
    "updated_at": "2026-09-03T14:00:00+08:00"
  },
  "action_cards": [
    {
      "card_id": "env_001",
      "type": "medication_storage",
      "title": "高温药品储存提醒",
      "content": "今日气温较高，请注意药品储存温度，避免阳光直射",
      "severity": "INFO",
      "related_member_ids": ["mem_001"],
      "valid_until": "2026-09-03T23:59:59+08:00"
    }
  ],
  "data_source": "local_weather_adapter",
  "disclaimer": "天气数据仅供参考，紧急情况请联系专业机构"
}
```

**隐私：** 仅发送城市/区县编码（6 位），不发送精确坐标。健康正文不出网。

**降级：** 天气服务不可用时返回 `degraded`，移动端显示「天气信息暂不可用」。

## 16. 联调指南

### 16.1 启动联调环境

```powershell
# 后端（独立 SQLite + 放开 CORS，端口 18800）
$env:DATABASE_URL = "sqlite+pysqlite:///./homecare-mobile-demo.sqlite3"
$env:CORS_ORIGINS = "http://localhost:5173,http://localhost:5175,capacitor://localhost"
$env:PYTHONPATH = "<主仓库>\src\api;<主仓库>\src"
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir src/api --host 0.0.0.0 --port 18800

# 造数
cd APP
npm run seed:live -- --base http://127.0.0.1:18800

# 移动端
npm run dev
```

### 16.2 常见联调问题

| 问题 | 原因 | 解决 |
| --- | --- | --- |
| CORS 错误 | 后端 CORS_ORIGINS 未包含移动端地址 | 检查环境变量，重启后端 |
| 401 所有接口 | 会话过期或未登录 | 重新登录，检查 token 是否携带 |
| 403 成员数据 | X-Access-Purpose 不匹配授权 | 检查授权 purpose 代码 |
| 404 资源 | 跨家庭访问或资源不存在 | 检查 household_id 是否正确 |
| 视觉任务一直 QUEUED | vision_worker 未启动 | 启动视觉 worker 或标记能力 unavailable |
| 助手回复空 | Ollama 未运行 | 启动 Ollama 或接受结构化降级 |
| 时间显示错误 | 家庭时区未配置 | PATCH household 设置 timezone |

### 16.3 调试技巧

1. **请求追踪：** 每个响应含 `X-Request-ID`，「我的 → 最近请求与回执」可查看
2. **API 文档：** 后端启动后访问 `http://localhost:18800/docs`（Swagger UI）
3. **远程调试：** Chrome 访问 `chrome://inspect`，调试 WebView
4. **日志查看：** 后端日志含 request_id，可按 ID 追踪完整请求链路
5. **造数脚本：** `APP/scripts/seed-live-demo.mjs` 生成虚构家庭数据，不含真实健康信息

## 17. 版本兼容性

### 17.1 向后兼容原则

- 新增字段不破坏旧客户端（旧客户端忽略未知字段）
- 接口路径不变，版本升级通过 `/api/v2` 新前缀
- 枚举值新增不破坏旧客户端（旧客户端显示原始值）
- 废弃接口至少保留一个发布周期，并在响应头添加 `Deprecation` 和 `Sunset`

### 17.2 客户端版本检查

应用启动时可调用 `/api/v1/meta/capabilities` 获取 `api_version`，与客户端支持的版本比对。版本不兼容时提示用户升级。

---

*本文档随后端 API 同步更新。如有与代码不一致之处，以 OpenAPI 文档（`/docs`）和最新合并的 PR 为准。*
