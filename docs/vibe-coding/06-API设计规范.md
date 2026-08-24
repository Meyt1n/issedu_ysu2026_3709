# HomeCare Twin API 设计规范

## 1. 通用约定

- 统一前缀 `/api/v1`，JSON 使用 `snake_case`，时间使用含时区 ISO 8601。
- 所有响应携带 `request_id`；写操作支持 `Idempotency-Key`。
- 列表使用游标分页；公开 ID 使用 UUID/ULID，不暴露自增序号。
- 认证只能证明用户身份；每次成员资源访问仍需校验家庭边界。
- P0 中，家庭 `owner` 是明确的家庭管理员，对本家庭的成员目录、健康事件和状态投影拥有管理范围内的完整访问；这个权限来自 `Household.created_by`，不由“子女/照护者”等角色名称推断，也不授予其他家庭。
- 非 owner 的照护者必须同时通过成员、字段、动作、目的和授权有效期检查；子女或照护者身份本身不能自动读取全部健康信息。
- P0 非 owner 通过 `X-Access-Purpose` 携带稳定的 ASCII 目的代码并与授权精确匹配；展示文案不得充当目的代码。
- 跨家庭、未授权以及成员/授权 ID 猜测统一返回 `404 RESOURCE_NOT_FOUND`，详细拒绝原因仅写入本地脱敏审计，避免接口泄露资源存在性。
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

错误码至少区分 `UNAUTHENTICATED`、`FORBIDDEN_MEMBER`、`CONSENT_REVOKED`、`VALIDATION_ERROR`、`AUTHORIZATION_VERSION_CONFLICT`、`IDEMPOTENCY_KEY_CONFLICT`、`EVENT_ALREADY_SUPERSEDED`、`OUT_OF_ORDER`、`CHECKPOINT_INVALID`、`FILE_REJECTED`、`MODEL_UNAVAILABLE`、`EVIDENCE_CONFLICT`、`EVIDENCE_INSUFFICIENT`、`RULE_VERSION_MISMATCH` 和 `RATE_LIMITED`。

## 2. 核心接口基线

> **2026-08-05 更新**：按实现阶段分为 P0（当前已实现）和 P1+（未来规划）。

### 2.1 P0 当前实现接口

| 方法 | 路径 | 用途 | 状态 |
|------|------|------|------|
| GET | `/health` | 服务健康检查 | ✅ |
| GET | `/api/v1/health/db` | 数据库连接检查 | ✅ |
| GET | `/api/v1/meta/capabilities` | 系统能力元数据 | ✅ |
| POST | `/api/v1/auth/register` | 使用 JSON 请求体注册本地账号 | ✅ |
| POST | `/api/v1/auth/login` | 使用 JSON 请求体建立短期 Bearer 会话 | ✅ |
| POST | `/api/v1/auth/logout` | 撤销当前短期会话 | ✅ |
| GET | `/api/v1/households` | 列出当前用户可见的家庭 | ✅ |
| POST | `/api/v1/households` | 创建家庭 | ✅ |
| PATCH | `/api/v1/households/{id}` | Owner 修改家庭业务时区 | ✅ |
| GET | `/api/v1/households/{id}/members` | 列出家庭成员 | ✅ |
| POST | `/api/v1/households/{id}/members` | 添加成员 | ✅ |
| GET | `/api/v1/households/{id}/authorizations` | Owner 查询本家庭授权 | ✅ |
| POST | `/api/v1/households/{id}/authorizations` | 创建字段级授权 | ✅ |
| PATCH | `/api/v1/households/{id}/authorizations/{auth_id}` | 按版本修改授权 | ✅ |
| POST | `/api/v1/households/{id}/authorizations/{auth_id}/revoke` | 撤销授权 | ✅ |
| GET | `/api/v1/households/{id}/authorization-audits` | Owner 查询授权与访问审计 | ✅ |
| GET | `/api/v1/households/{id}/authorization-audits/page` | Owner 按签名游标分页查询审计，可按 `request_id`、`action`、`outcome` 过滤；游标绑定全部筛选范围 | ✅ |
| POST | `/api/v1/households/{id}/events` | 追加健康事件 | ✅ |
| GET | `/api/v1/households/{id}/events` | 查询事件列表 | ✅ |
| GET | `/api/v1/households/{id}/events/page` | 按授权范围分页查询事件，可按 `member_id`、`event_type`、`confirmation_status`、`occurred_from`、`occurred_until` 过滤；游标绑定全部筛选范围 | ✅ |
| POST | `/api/v1/households/{id}/events/{event_id}/compensations` | 追加补偿事件 | ✅ |
| GET | `/api/v1/households/{id}/members/{mid}/state` | 查询成员状态投影 | ✅ |
| POST | `/api/v1/households/{id}/members/{mid}/state/checkpoints` | 创建投影 checkpoint | ✅ |
| POST | `/api/v1/households/{id}/members/{mid}/state/replay` | 从空状态/checkpoint 重放 | ✅ |
| GET | `/api/v1/households/{id}/outbox` | Owner 查询 outbox 恢复状态 | ✅ |
| POST | `/api/v1/households/{id}/outbox/dispatch` | Owner 手工触发恢复批次 | ✅ |

P0 错误格式：当前使用 FastAPI 默认 `{"detail":"..."}`，P1 统一为 `{"error":{"code":"...","message":"...","details":{},"request_id":"..."}}`。

家庭接口的 `HouseholdRead.time_zone` 是服务端业务日的 IANA 时区名称。创建家庭可传入时区，省略时使用部署配置 `DEFAULT_HOUSEHOLD_TIME_ZONE`；只有家庭 Owner 可通过 `PATCH /api/v1/households/{id}` 修改该字段，非法时区返回校验错误。该字段只影响业务日展示，不参与身份或授权判断。

HCT-417 Web 会话边界：注册、登录和登出只接受 JSON 请求体，密码不得出现在 URL、日志或前端持久化存储中。登录返回 `actor_id`、短期 `session_token` 和 `expires_at`；除登录/注册外，正式网页请求使用 `Authorization: Bearer <session_token>`，Bearer 身份优先于 `X-Actor-Id`。令牌当前只保存在页面内存，浏览器收到 `401` 时必须清理家庭、成员、健康数据和会话状态并回到登录页。`X-Actor-Id` 仅保留给明确的非生产本地演示；正式部署还必须补齐持久化会话存储、密钥轮换、CSRF/同源策略和会话撤销审计，不能把本地内存实现直接宣称为生产鉴权。

P0 权限边界的事实源是：owner 可访问本家庭成员目录和健康事件/状态；非 owner 只能看到授权成员和字段。若未来改为 owner 也必须逐项授权，必须先更新 Story、ADR、OpenAPI 和契约测试，不能由单个 PR 默默改变。

授权创建返回 `grantor_actor_id`、`version=1`、`created_at` 和 `updated_at`。更新请求至少包含一个变更字段及 `expected_version`；撤权请求包含 `expected_version`。数据库只在当前版本相等时更新并把版本加一，否则返回 `409 AUTHORIZATION_VERSION_CONFLICT`。已撤销授权不可再次修改。

`access_audit` 是追加写最小证明：记录授权 ID、操作者、动作、数据域、目的、允许/拒绝、原因和前后版本，不记录健康正文、证据或状态快照。授权审计只允许本家庭 Owner 查询。已有审计时禁止通过数据库 downgrade 删除历史记录。

HCT-103 事件写入支持最长 128 位 `Idempotency-Key`。家庭、key、操作、操作者和规范请求体相同则返回原事件；同 key 对应不同指纹返回 `409 IDEMPOTENCY_KEY_CONFLICT`。事件响应包含成员内 `sequence_no`、发生/记录时间、`correlation_id`、`causation_id`、`supersedes_event_id` 和 `schema_version`。补偿只能引用本家庭、本成员的已确认事件，原事件不可修改。

事件、最小 outbox 和在线投影在同一事务提交。outbox 不保存健康 payload，只保存事件引用、成员序号、确认状态和 Schema 版本；自动 worker 及手工恢复接口使用 `PENDING/PROCESSING/FAILED/DISPATCHED`、尝试次数、锁和稳定错误码。投影返回 `last_sequence`、`version` 和状态哈希；重放只允许家庭 Owner，checkpoint 哈希或家庭/成员不匹配返回 `409 CHECKPOINT_INVALID`。

### 2.2 视觉与人工复核 P0 接口

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/vision-tasks` | 使用安全文件引用和成员 ID 创建视觉任务 |
| POST | `/vision-tasks/{id}/evidence` | 保存本地适配器签名的 OCR-first 证据 |
| POST | `/vision-tasks/{id}/fusion` | 融合批准主数据候选并创建唯一待复核任务 |
| GET | `/vision-tasks/{id}` | 查询任务、版本和证据结果 |
| POST | `/vision-tasks/{id}/retry` | 失败/超时任务原地重新排队，不创建第二个任务 |
| GET | `/households/{household_id}/members/{member_id}/review-tasks` | 查询有权限成员的待复核任务 |
| GET | `/households/{household_id}/review-tasks/{id}` | 查询单个复核任务和版本 |
| POST | `/households/{household_id}/review-tasks/{id}/confirm` | 确认候选并追加健康事件 |
| POST | `/households/{household_id}/review-tasks/{id}/correct` | 人工修正并追加健康事件 |
| POST | `/households/{household_id}/review-tasks/{id}/skip` | 跳过复核且不创建健康事件 |

视觉任务必须绑定真实 `member_id`，服务端由成员反查家庭并校验 `health_events` 数据域、目的和有效期，禁止使用占位家庭。创建、证据提交和取消要求 `WRITE_EVENTS`，查询要求 `READ_EVENTS`，融合因读取已有证据并创建复核任务而同时要求两者；每次请求都重新鉴权，撤权后统一隐藏资源。视觉任务创建的同 key、同完整请求（含文件、成员及全部模型/Schema/代码/数据版本）并发重试只产生并返回一条任务，异载荷返回 `409 IDEMPOTENCY_KEY_CONFLICT`。融合响应增加 `review_task_id` 和 `review_task_version`；同一视觉任务只能有一个复核任务，并持久化覆盖阈值、权重、版本、状态和候选的规范化指纹。完全相同的重试返回原任务，配置或输入变化返回 `409 REVIEW_TASK_FUSION_CONFLICT`。

复核任务读取要求 `READ_EVENTS`；确认、修正和跳过因响应包含完整候选而同时要求 `READ_EVENTS` 与 `WRITE_EVENTS`，并必须携带 `expected_version`。确认和修正应携带最长 128 位 `Idempotency-Key`。服务端以 `status=PENDING_REVIEW AND version=expected_version` 条件更新争抢转换权。只有争抢成功的请求能在同一数据库事务追加一个已确认事件及一个 outbox；并发失败返回 `409 REVIEW_VERSION_CONFLICT` 或终态错误。同 key、同载荷、同操作者重试返回原转换，不再创建事件；更换候选、人工值、备注或跳过原因返回 `409 IDEMPOTENCY_KEY_CONFLICT`。无成员级权限、跨家庭或撤权访问统一返回资源不存在。

### 2.3 P1+ 未来规划接口

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
| GET | `/households/{household_id}/members/{member_id}/plan-workbench` | 按家庭时区读取计划、动作历史、逾期和疗程结束状态 |
| POST | `/households/{household_id}/members/{member_id}/plans/evaluate` | Owner 对明确授权的计划执行幂等漏服、疗程结束与照护升级评估 |
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

只有 `CONFIRMED`/`CORRECTED` 可触发正式状态投影、风险计算和药物计划；融合结果只创建 `PENDING_REVIEW`，不得先写健康事件。状态转换使用数据库条件更新和单调 `version` 乐观锁，重复复核保持幂等。返回值必须包含模型/OCR/匹配器版本、证据帧、字段来源和人工确认状态。`CORRECTED` 必须返回原预测、修正值、修正原因、操作者和训练同意状态。

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

`POST /assistant/chat` 只执行白名单只读工具。`retrieve_knowledge` 必须使用请求中的 `household_id`/`member_id`，模型不得改写范围。最终 `citations` 只能引用本次工具返回的 `document_id`/`version`/`chunk_id`；伪造来源返回 `CITATION_NOT_FOUND`，无授权文档返回 `NO_AUTHORISED_DOCUMENTS`。降级响应的 `sources` 和 `citations` 必须为空。

助手响应中的引用展示字段（标题、片段正文、定位）只能从同一轮已授权检索结果透传，不能由模型生成或由前端补猜；它们用于解释展示，不改变引用的身份校验。前端只在当前标签页保存按身份/家庭/成员隔离的临时会话，不新增服务端会话存储。

语音输入不新增 API：浏览器只把用户主动授权后的识别文字写入聊天草稿，用户发送后沿用本接口；服务端不接收或保存音频。语音回复由客户端浏览器本地 `speechSynthesis` 按用户操作播放，不改变回答、引用、权限或审计契约。

正常回答可返回 `suggested_questions`（最多 3 条）作为交互提示。该字段只由最新用户问题的受控意图模板生成，不是事实、规则、健康事件或模型思考链；建议必须去重、限长、无外链/广告/问诊导流/医疗指令。模型不可用、无证据降级、引用校验失败或请求失败时返回空数组，客户端不得把建议写入健康事实。

回答接口必须明确返回 `route`、证据完整性和降级状态。模型不可用时只能返回结构化事实/规则结果或 `MODEL_UNAVAILABLE`，不得把云端服务当作家庭版默认回退。

## 5. 并发、审计与删除

成员状态、计划和授权更新使用版本号/ETag 防止覆盖；P0 授权 API 使用请求体 `expected_version` 实现 compare-and-swap。所有敏感写操作记录操作者、目标、目的、前后版本和结果。

家庭 Owner 可调用 `DELETE /households/{household_id}` 触发完整删除传播，可选 `member_id` 仅擦除一名成员。接口同步执行本地传播链并返回清理任务：`id`、`status`、各层 `layers`（`database` / `files` / `vectors` / `cache` / `hard_samples` / `backups` / `audit`）和脱敏 `scope`。`GET /erasure-tasks/{task_id}` 供同一请求者查询处置状态。主库对家庭/成员写入 `deleted_at` 软删除，业务读取返回 `RESOURCE_NOT_FOUND`；`health_event` 保持物理不可变，仅对已擦除范围隐藏。对象文件、家庭范围知识块、缓存目录和困难样本按层清理；`FILE_ROOT/backup-skip/{task_id}.json` 标记恢复时跳过，备份脚本复制该目录。审计与 skip 标记只保留 `deletion_id`、操作者、范围 ID 和计数，禁止 `payload` / `evidence` / `state` / `display_name`。这不表示改写已离线的生产灾备副本。

## 6. 契约管理

OpenAPI 是接口事实源。破坏性变化必须新版本或迁移期；Schema、SDK、Mock、契约测试和本文同时更新。Mock 只用于开发，不得作为功能完成证据。

风险“已知晓”回写必须使用服务端重新计算的规则版本和风险指纹；`POST /households/{household_id}/members/{member_id}/risks/{rule_id}/acknowledge` 必须携带 `Idempotency-Key`。接口只返回最小回执（操作者、服务端时间、规则版本和指纹），不得写入风险消息、健康正文、证据正文或图片。授权撤回、过期、目的不匹配、风险失效和版本变化必须拒绝或隐藏，重复幂等键只能返回原回执。

