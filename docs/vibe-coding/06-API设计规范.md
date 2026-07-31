# API 设计规范

## 1. 通用约定

- 基础路径：`/api/v1`；破坏性变化升级主版本。
- JSON 字段使用 `snake_case`，时间使用带时区的 ISO 8601 UTC。
- 资源使用复数名词，如 `/users`、`/documents`，动作用子资源表达。
- 成功创建返回 `201`，异步任务返回 `202`，删除成功返回 `204`。
- 分页统一使用 `page_size` 和不透明 `cursor`。
- 每个响应返回或响应头携带 `request_id`。

## 2. 统一错误

```json
{
  "error": {
    "code": "VISION_LOW_CONFIDENCE",
    "message": "无法可靠识别该图片，请重新拍摄或人工核对",
    "request_id": "req_01...",
    "details": {}
  }
}
```

`message` 可展示给用户且不泄露内部细节；`code` 稳定可编程；堆栈只进入受控日志。

## 3. 认证与幂等

- `Authorization: Bearer <access_token>`，访问令牌短时有效。
- 刷新令牌单独存储、轮换并可撤销。
- 创建任务、上传、导出等重试操作支持 `Idempotency-Key`。
- 所有资源按当前用户和授权范围查询，禁止先查出再由前端隐藏。

## 4. 核心接口草案

| 方法与路径                                  | 说明             | 权限              |
| ------------------------------------------- | ---------------- | ----------------- |
| `POST /auth/login`                          | 登录             | 公开、限流        |
| `POST /auth/refresh`                        | 刷新令牌         | 持有刷新令牌      |
| `GET /family-members`                       | 家庭成员列表     | 本人/已授权       |
| `POST /vision/drug-detections`              | 创建单图识别任务 | 登录用户          |
| `GET /tasks/{task_id}`                      | 查询异步任务     | 任务所有者        |
| `POST /knowledge/documents`                 | 上传知识文档     | 内容权限          |
| `POST /knowledge/documents/{id}/index-jobs` | 建立索引         | 文档所有者/管理员 |
| `POST /chats`                               | 创建会话         | 登录用户          |
| `POST /chats/{id}/messages`                 | 发送多模态消息   | 会话所有者        |
| `GET /audit-events`                         | 查询脱敏审计     | 管理员            |
| `DELETE /me/data`                           | 发起个人数据删除 | 本人、二次认证    |

### 4.1 一期候选接口

| 方法与路径                               | 说明                    | 权限                   |
| ---------------------------------------- | ----------------------- | ---------------------- |
| `POST /api/v1/auth/register`             | 注册，邮箱规范化唯一    | 公开                   |
| `POST /api/v1/auth/login`                | 登录并签发访问/刷新令牌 | 公开                   |
| `POST /api/v1/auth/refresh`              | 轮换刷新令牌            | 持有有效刷新令牌       |
| `POST /api/v1/auth/logout`               | 撤销刷新令牌            | 持有刷新令牌           |
| `GET /api/v1/users/me`                   | 当前用户信息            | 登录用户               |
| `POST/GET /api/v1/families`              | 创建/列出可访问家庭     | 登录用户               |
| `GET /api/v1/families/{id}`              | 家庭详情                | 成员或有效授权         |
| `POST/GET /api/v1/families/{id}/members` | 添加/列出成员           | 添加需 owner/caregiver |
| `POST/GET /api/v1/consent-grants`        | 创建/列出授权           | 创建需家庭 owner       |
| `DELETE /api/v1/consent-grants/{id}`     | 立即撤销授权            | 授权人                 |
| `GET /api/v1/audit-events`               | 当前用户脱敏审计        | 登录用户               |
| `GET /api/v1/health`                     | 进程存活检查            | 公开                   |
| `GET /api/v1/ready`                      | 数据库就绪检查          | 公开                   |

以上接口均为待评审契约，当前尚未实现。启动开发后，运行时 OpenAPI 计划使用
`/openapi.json`，Swagger UI 计划使用 `/docs`，ReDoc 计划使用 `/redoc`；所有响应计划
通过 `X-Request-ID` 头返回请求 ID。实际路径以已合并 OpenAPI 和契约测试为准。

### 4.2 一期错误码规划

认证计划使用 `AUTH_*`，家庭权限使用 `FAMILY_*`，授权使用 `CONSENT_*`，依赖故障使用
`DEPENDENCY_*`。校验失败候选码为 `REQUEST_VALIDATION_FAILED`；错误详情只返回字段位置和
错误类型，不回显密码、令牌或医疗正文。错误码在首个契约评审后冻结，冻结前不得称为稳定接口。

## 5. AI 响应最低字段

```json
{
  "result": {},
  "confidence": 0.82,
  "uncertainty": "medium",
  "model_version": "drug-detector@1.2.0",
  "knowledge_version": "medical-public@2026-07",
  "citations": [],
  "safety": {
    "level": "informational",
    "disclaimer": "仅供健康信息参考，不替代医生诊断。"
  },
  "request_id": "req_01..."
}
```

不适用字段可省略，但问答必须有安全信息，药物识别必须有置信度和模型版本。

## 6. 文件与流式接口

- 文件先获取受限上传凭证，服务端复核 MIME、扩展名、大小和哈希。
- 不接受客户端提供的本地路径或对象存储内部地址。
- 问答流式输出使用 SSE；每个事件包含类型、序号和请求 ID。
- 视频使用 WebSocket/WebRTC 时必须定义心跳、断线、背压和最大帧率。

## 7. 契约管理

- OpenAPI 是接口事实来源，代码、SDK 和测试从同一契约生成或校验。
- 示例只使用虚构数据。
- 破坏性修改必须提供迁移期、弃用标头和变更说明。
- 合并前运行契约测试，保证错误结构、权限和关键字段不回退。
