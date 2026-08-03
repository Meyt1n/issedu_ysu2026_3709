# HomeCare Twin API 设计规范

## 1. 通用约定

- 统一前缀 `/api/v1`，JSON 使用 `snake_case`，时间使用含时区 ISO 8601。
- 所有响应携带 `request_id`；写操作支持 `Idempotency-Key`。
- 列表使用游标分页；公开 ID 使用 UUID/ULID，不暴露自增序号。
- 认证只能证明用户身份；每次成员资源访问仍需家庭与成员级授权。
- 每次成员资源访问还需通过字段级可见范围、动作、目的和授权有效期检查；子女不能因角色自动读取全部健康信息。
- 文件上传采用白名单 MIME、大小/像素/时长限制和内容探测。
- 家庭版 API 不提供云端模型回退；网络出口仅由受控适配器使用，健康上下文不得出网。

统一错误：

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

错误码至少区分 `UNAUTHENTICATED`、`FORBIDDEN_MEMBER`、`CONSENT_REVOKED`、`VALIDATION_ERROR`、`FILE_REJECTED`、`MODEL_UNAVAILABLE`、`EVIDENCE_CONFLICT`、`EVIDENCE_INSUFFICIENT`、`RULE_VERSION_MISMATCH` 和 `RATE_LIMITED`。

## 2. 核心接口基线

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/vision/jobs/image` | 创建图片识别任务 |
| POST | `/vision/jobs/video` | 创建视频抽帧识别任务 |
| GET | `/vision/jobs/{id}` | 查询进度、候选和证据 |
| POST | `/recognitions/{id}/review` | 确认、纠正或拒绝结果 |
| GET | `/recognitions/{id}/evidence` | 查看 OCR、条码、包装特征、主数据和模型版本 |
| POST | `/health-events` | 创建手工健康事件 |
| GET | `/members/{id}/timeline` | 获取成员事件时间线 |
| GET | `/members/{id}/visibility` | 返回当前调用者可见字段与动作 |
| POST | `/consents` | 创建成员/字段/动作/目的/期限授权 |
| POST | `/consents/{id}/revoke` | 立即撤权并触发缓存/索引清理 |
| GET | `/graph/members/{id}` | 获取家庭健康关系投影 |
| POST | `/risks/evaluate` | 以指定状态/规则版本重算风险 |
| POST | `/plans/{id}/optimize` | 生成安全时间窗内提醒建议 |
| POST | `/plans/{id}/approve` | 人工批准计划版本变化 |
| GET | `/environment/actions` | 获取环境行动卡 |
| POST | `/assistant/chat` | 调用受约束本地助手 |
| POST | `/models/retrain` | 管理员创建追加训练任务 |
| GET | `/dashboard/family` | 家庭业务大屏 |
| GET | `/dashboard/model` | 模型技术大屏 |

实际实现可增加 `/auth`、`/families`、`/members`、`/consents`、`/documents`、`/medicines` 和 `/tasks` 资源，但必须先更新 OpenAPI 和追踪矩阵。

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
