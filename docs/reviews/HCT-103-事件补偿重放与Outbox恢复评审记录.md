# HCT-103 事件补偿、重放与 Outbox 恢复评审记录

## 1. 评审元数据

- Story：HCT-103
- Issue：[#44](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/44)
- 需求：FR-02、NFR-03
- 风险：R3
- 负责人：Meyt1n（实现协作：Codex）
- 复核方式：维护者检查本记录、PR 差异与 Required Checks 后执行 merge，即完成最终人工复核
- 日期：2026-08-08

## 2. 当前结论

实现、自动回归和隔离 MySQL 8.4 故障恢复验收已完成，结论为“可进入 PR 复核”。本 Story 只证明手工事件的不可变追加、补偿、幂等、outbox 恢复和投影重放；视觉识别、规则、图谱、计划、删除传播和完整页面仍未交付。

## 3. 威胁与控制

| 威胁 | 控制 | 证据 |
|---|---|---|
| API 重试追加重复事实 | 家庭级幂等唯一约束 + 操作/操作者/payload 指纹 | `test_same_idempotency_key_returns_one_result_and_rejects_conflict` |
| 更正覆盖原历史 | 补偿事件引用 `supersedes_event_id`；MySQL/SQLite 触发器拒绝 UPDATE/DELETE | 补偿测试、迁移测试、MySQL `ERROR 1644 HEALTH_EVENT_IMMUTABLE` |
| 事件、outbox 和投影分裂 | 单事务写入，投影异常统一 rollback | `test_projection_failure_rolls_back_event_and_outbox_atomically` |
| worker 失败或崩溃丢消息 | 状态/尝试/锁/错误码 + 过期锁回收 + 本地常驻 worker | 失败重试测试、隔离容器中断恢复 |
| 重复投递重复生效 | 投影 `last_sequence`/版本防重 | `test_outbox_failure_stale_lock_and_duplicate_delivery_are_recoverable` |
| 乱序跨过缺失事实 | 查询已确认前序，缺口返回 `OUT_OF_ORDER` | `test_out_of_order_delivery_waits_for_missing_confirmed_event` |
| checkpoint 被篡改或串家庭 | 家庭/成员绑定 + 规范 JSON SHA-256 校验 | 重放服务与契约测试 |
| outbox/日志复制健康正文 | outbox 只保存 ID、序号、确认和 Schema 版本；worker 只输出计数/稳定码 | 模型列检查、worker 日志 |

## 4. MySQL 8.4 Compose 证据

隔离项目 `hct103verify` 使用端口 33308/18002/18082 和纯合成家庭、成员及 NOTE 事件。首次空库验证发现 MySQL 8.4 启用 binary log 时，受限项目账号创建触发器需要 `log_bin_trust_function_creators=1`；已在 Compose MySQL 基线显式配置，从删除卷后的全新空库重新构建并通过，未复用半迁移状态。

最终结果：

```json
{
  "migration_head": "0004_hct103_event_recovery",
  "duplicate_same_id": true,
  "correction_sequence": 2,
  "supersedes_original": true,
  "checkpoint_sequence": 1,
  "replay_consistent": true,
  "replayed_from_checkpoint": 1,
  "state_sequence": 2,
  "active_event_count": 1,
  "outbox_initial": ["DISPATCHED", "DISPATCHED"],
  "immutability_triggers": 2,
  "direct_update": "HEALTH_EVENT_IMMUTABLE",
  "interrupted_message_recovered": 1,
  "api_health": "ok",
  "web_health": 200,
  "worker_health": "healthy"
}
```

worker 中断演练：停止 worker 后追加第 3 条合成事件，把其 outbox 标记为 10 分钟前的 `PROCESSING`，再启动 worker。日志记录 `recovered_stale=1`、`dispatched=1`，消息最终为 `DISPATCHED` 且 `attempts=1`。worker 日志没有事件 payload、evidence 或成员状态。

## 5. 质量检查

| 检查 | 结果 |
|---|---|
| `uv run ruff check src/api src/ai scripts tests migrations` | 通过 |
| `CI=true uv run pytest` | `126 passed, 5 skipped`；补充 worker CI 用例后以最终 PR 日志为准 |
| `npm run check:web` | 通过 |
| `npm run build:web` | 通过，Vite 生产构建成功 |
| `docker compose config --quiet` | 通过 |
| `git diff --check` | 通过 |
| SQLite 既有事件升级与不可变触发器 | 通过 |
| MySQL 8.4 空库迁移、四服务健康和事件实链 | 通过 |

本机非 CI 全量测试中的 GitHub 连通性用例会受全局失效代理 `127.0.0.1:7890` 影响；业务回归使用 `CI=true` 按仓库规则跳过外部连通性测试，GitHub Actions 在 Linux 环境独立复核。

## 6. 回滚与后续边界

- 回滚应用前先停止 outbox worker；保留 `health_event`、`outbox_message`、投影和 checkpoint，不手工改写事件。
- 有事件时 migration downgrade 主动拒绝；使用兼容应用或前滚修复。空事件库才允许结构降级。
- HCT-207 的视觉人工复核事务必须调用本 Story 的事件应用服务，不能建立旁路或把 `UNCONFIRMED` 结果写入正式状态。
- HCT-301 的关系投影与全量重建必须复用成员序号、状态哈希、checkpoint 和 outbox 恢复语义。
- HCT-104 文件、HCT-106 字段视图和 HCT-107 真实身份仍未完成，本 Story 不代表完整 FR-01/FR-02 页面交付。
