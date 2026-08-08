# HCT-204：视觉任务 API、本地文件引用、状态与版本登记

- 需求：FR-03
- 状态：进行中
- 负责人：Shen-huang-123
- 复核人：待项目组指定
- 风险：R3；任务状态丢失或文件引用越权将导致证据链断裂
- 依赖：HCT-101、HCT-202
- 允许修改：`src/api/app/models.py`、`src/api/app/routes.py`、`src/api/app/schemas.py`、`migrations/versions/`、`src/ai/vision/`、`tests/`

## 用户价值

视觉识别任务以稳定异步 API 连接已授权文件、预处理和下游证据管线——支持幂等创建、可恢复执行和完整结果追踪。

## 范围与非目标

**范围：**
- 仅接受已授权 `file_id`，拒绝本地路径/外部 URL
- 六状态任务机：queued → running → succeeded/failed/cancelled/timeout
- 幂等创建，取消/超时/重启可恢复
- 结果记录预处理、模型、阈值、Schema、版本和输入完整性引用
- OpenAPI 同步、DB 迁移、日志脱敏

**明确不做：**
- 请求中不传大文件 Base64
- 不做候选融合和自动健康事件确认

## Given / When / Then

- Given 已授权 file_id；When 创建视觉任务；Then 返回 task_id，状态 queued。
- Given 相同 file_id + 相同参数重复提交；When 幂等检查命中；Then 返回已有 task_id，不重新执行。
- Given worker 异常退出；When 重启；Then queued 和 running 任务可恢复执行或标记超时。
- Given 任务结果输出；When 记录日志；Then 不含文件正文、绝对路径或密钥。

## 测试与证据

- 未认证/未授权文件拒绝
- 幂等创建、非法状态转换、取消/超时
- Worker 重启恢复
- API 契约 + 迁移 + 日志脱敏验证

## 部署与回滚

暂停 worker 和新任务创建 → 保留任务/文件审计 → 回滚 API/Schema 版本 → 未完成任务标记为可安全重试。
