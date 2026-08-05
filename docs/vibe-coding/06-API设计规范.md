# HomeCare Twin API 设计规范

## 1. 通用约定

- 统一前缀 `/api/v1`，JSON 使用 `snake_case`，时间使用含时区 ISO 8601。
- 所有响应携带 `request_id`；写操作支持 `Idempotency-Key`。
- 列表使用游标分页；公开 ID 使用 UUID/ULID，不暴露自增序号。
- 认证只能证明用户身份；每次成员资源访问仍需家庭与成员级授权。
- 每次成员资源访问还需通过字段级可见范围、动作、目的和授权有效期检查；子女不能因角色自动读取全部健康信息。
- 文件上传采用白名单 MIME、大小/像素/时长限制和内容探测。
- 家庭版 API 不提供云端模型回退；网络出口仅由受控适配器使用，健康上下文不得出网。

统一错误（P1 目标格式，P0 使用 FastAPI 默认 `{"detail":"..."}` 格式）：

```json
{
  "error": {
    "code": "RECOGNITION_REVIEW_REQUIRED",
    "message": "识别证据存在冲突，需要人工复核",
    "details": {},
    "request_id": "01..."
  }
}
```

> **P0 过渡方案**：当前实现使用 FastAPI 默认错误格式（`{"detail":"..."}`），P1 统一为上述 `error.code` 格式。前端应兼容两种格式。

错误码至少区分 `UNAUTHENTICATED`、`FORBIDDEN_MEMBER`、`CONSENT_REVOKED`、`VALIDATION_ERROR`、`FILE_REJECTED`、`MODEL_UNAVAILABLE`、`EVIDENCE_CONFLICT`、`EVIDENCE_INSUFFICIENT`、`RULE_VERSION_MISMATCH` 和 `RATE_LIMITED`。

## 2. 核心接口基线

> **2026-08-05 更新**：按实现阶段分为 P0（当前已实现）和 P1+（未来规划）。

### 2.1 P0 当前实现接口

| 方法 | 路径 | 用途 | 状态 |
|------|------|------|------|
| GET | `/health` | 服务健康检查 | ✅ |
| GET | `/api/v1/health/db` | 数据库连接检查 | ✅ |
| GET | `/api/v1/meta/capabilities` | 系统能力元数据 | ✅ |
| GET | `/api/v1/households` | 列出当前用户可见的家庭 | ✅ |
| POST | `/api/v1/households` | 创建家庭 | ✅ |
| GET | `/api/v1/households/{id}/members` | 列出家庭成员 | ✅ |
| POST | `/api/v1/households/{id}/members` | 添加成员 | ✅ |
| POST | `/api/v1/households/{id}/authorizations` | 创建字段级授权 | ✅ |
| POST | `/api/v1/households/{id}/authorizations/{auth_id}/revoke` | 撤销授权 | ✅ |
| POST | `/api/v1/households/{id}/events` | 追加健康事件 | ✅ |
| GET | `/api/v1/households/{id}/events` | 查询事件列表 | ✅ |
| GET | `/api/v1/households/{id}/members/{mid}/state` | 查询成员状态投影 | ✅ |

P0 错误格式：当前使用 FastAPI 默认 `{"detail":"..."}`，P1 统一为 `{"error":{"code":"...","message":"...","details":{},"request_id":"..."}}`。

### 2.2 P1+ 未来规划接口

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/vision/jobs/image` | 创建图片识别任务 |
| POST | `/vision/jobs/video` | 创建视频抽帧识别任务 |
| GET | `/vision/jobs/{id}` | 查询进度、候选和证据 |
| POST | `/recognitions/{id}/review` | 确认、纠正或拒绝结果 |
| GET | `/recognitions/{id}/evidence` | 查看 OCR、条码、包装特征等 |
| GET | `/members/{id}/timeline` | 成员事件时间线 |
| GET | `/members/{id}/visibility` | 当前调用者可见字段与动作 |
| GET | `/graph/members/{id}` | 家庭健康关系投影 |
| POST | `/risks/evaluate` | 重算风险 |
| POST | `/plans/{id}/optimize` | 生成提醒建议 |
| POST | `/plans/{id}/approve` | 人工批准计划 |
| GET | `/environment/actions` | 环境行动卡 |
| POST | `/assistant/chat` | 本地助手 |
| POST | `/models/retrain` | 追加训练 |
| GET | `/dashboard/family` | 家庭大屏 |
| GET | `/dashboard/model` | 模型大屏 |

## 3. 视觉任务状态机

```text
QUEUED -> PREPROCESSING -> INFERENCING -> FUSING
       -> MATCHED | CONFLICT | UNKNOWN | REVIEW | FAILED
MATCHED/CONFLICT/UNKNOWN/REVIEW -> CONFIRMED | CORRECTED | REJECTED
```

只有 `CONFIRMED`/`CORRECTED` 可触发健康事件；状态转换使用乐观锁，重复复核保持幂等。返回值必须包含模型/OCR/匹配器版本、证据帧、字段来源和人工确认状态。`CORRECTED` 必须返回原预测、修正值、修正原因、操作者和训练同意状态。

## 4. 证据契约

风险卡和助手证据型响应至少包含：

```json
{
  "answer": "...",
  "route": "EVIDENCE_REQUIRED",
  "facts": [{"fact_id": "...", "event_id": "...", "confirmed": true}],
  "rules": [{"rule_id": "...", "version": "...", "level": "HIGH"}],
  "citations": [{"document_id": "...", "version": "...", "chunk_id": "..."}],
  "actions": [{"type": "REVIEW", "assignee_role": "MEMBER"}],
  "visibility": {"member_id": "...", "fields": ["medication.summary"], "expires_at": "..."},
  "model_version": "...",
  "knowledge_version": "...",
  "request_id": "..."
}
```

`EVIDENCE_REQUIRED` 没有引用时不得返回肯定性回答。客户端不得只展示 `answer` 而隐藏规则和确认状态。

回答接口必须明确返回 `route`、证据完整性和降级状态。模型不可用时只能返回结构化事实/规则结果或 `MODEL_UNAVAILABLE`，不得把云端服务当作家庭版默认回退。

## 5. 并发、审计与删除

成员状态、计划和授权更新使用版本号/ETag 防止覆盖；所有敏感写操作记录操作者、目标、目的、前后版本和结果。删除接口返回清理任务 ID，支持查询主库、文件、向量索引、缓存和备份处置状态。

## 6. 契约管理

OpenAPI 是接口事实源。破坏性变化必须新版本或迁移期；Schema、SDK、Mock、契约测试和本文同时更新。Mock 只用于开发，不得作为功能完成证据。
