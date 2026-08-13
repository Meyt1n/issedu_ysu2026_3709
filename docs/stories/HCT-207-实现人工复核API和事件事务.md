# HCT-207 实现人工复核 API、幂等确认和事件事务

## 任务元数据

- Story：HCT-207
- FR/NFR：FR-02、FR-03、NFR-03、NFR-07
- 阶段：P0-W4
- 风险：R3
- 主责角色：后端组长 + 前端组长
- 负责人：Shen-huang-123 (Wind)
- 复核人：待定；R3 任务不得由负责人自我复核
- 前置依赖：HCT-103、HCT-106、HCT-301
- 当前状态：In Progress
- 规划依据：PR #36 与 docs/vibe-coding/19-项目全生命周期开发流程.md

## 目标与价值

让家庭成员核对多证据候选、纠正错误并以一次可审计事务生成确认后的健康事件。

## 范围

实现复核详情、候选选择/手工修正、二次确认、幂等提交、并发冲突、事件/outbox 事务和结果页面。

## 明确不做

不把模型结果默认选中后静默提交，不允许修改已确认历史事件。

## 验收标准

- [ ] 页面展示原图/关键证据、候选支持与冲突、模型/规则版本以及明确的未确认状态
- [ ] 用户必须主动选择或修正并完成确认；UNKNOWN/CONFLICT 不能被后台自动提交
- [ ] 确认 API 校验权限、任务版本和幂等键，并发或重复点击只生成一个健康事件
- [ ] 复核结果、健康事件和 outbox 在同一事务提交，失败时全部回滚且可重试
- [ ] 修正通过新事件和差异记录表达，时间线能区分机器候选、人工确认和后续补偿

## 设计决策

### 状态机

```
PENDING_REVIEW  →  CONFIRMED   (用户确认)
PENDING_REVIEW  →  CORRECTED   (用户修正)
PENDING_REVIEW  →  SKIPPED     (用户跳过)
CONFIRMED       →  (只读，不可修改)
CORRECTED       →  (只读，不可修改)
```

### 幂等设计

- 每个复核任务有唯一的 `task_id`
- 确认/修正请求携带 `idempotency_key`
- 相同 key 的重复请求返回相同结果，不重复落库
- 并发请求通过数据库行锁 + 乐观版本号处理

### 四状态处理

| 状态 | 视觉候选 | 用户可操作 | 自动提交 |
|------|---------|-----------|---------|
| MATCHED | 高置信度单候选 | 确认/修正/跳过 | ❌ 禁止 |
| CONFLICT | 多个冲突候选 | 选择其一/修正/跳过 | ❌ 禁止 |
| UNKNOWN | 无可识别候选 | 手动录入/跳过 | ❌ 禁止 |
| LOW_QUALITY | 低置信度候选 | 确认/修正/跳过 | ⚠️ 需二次确认 |

## 数据库变更

新增 `review_task` 表：

```sql
CREATE TABLE review_task (
    id              VARCHAR(36) PRIMARY KEY,
    vision_task_id  VARCHAR(36) NOT NULL,       -- 关联视觉任务
    household_id    VARCHAR(36) NOT NULL,
    member_id       VARCHAR(36) NOT NULL,
    status          VARCHAR(32) NOT NULL,       -- PENDING_REVIEW/CONFIRMED/CORRECTED/SKIPPED
    fusion_status   VARCHAR(32),                 -- MATCHED/CONFLICT/UNKNOWN/LOW_QUALITY
    candidates      JSON NOT NULL,               -- 视觉候选列表
    selected_candidate JSON,                     -- 用户选择的候选
    manual_payload  JSON,                        -- 用户手工修正内容
    idempotency_key VARCHAR(128),                -- 幂等键
    confirmed_by    VARCHAR(120),                -- 确认人 actor_id
    confirmed_at    TIMESTAMPTZ,                 -- 确认时间
    model_version   VARCHAR(64),                 -- 模型版本
    rule_version    VARCHAR(64),                 -- 规则版本
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

## API 设计

### 复核详情

```
GET /api/v1/households/{household_id}/review-tasks/{task_id}
```

**响应：**
```json
{
  "id": "uuid",
  "vision_task_id": "uuid",
  "status": "PENDING_REVIEW",
  "fusion_status": "MATCHED",
  "candidates": [
    {
      "drug_name": "A",
      "confidence": 0.92,
      "evidence": ["ocr_text", "barcode_data"],
      "dosage": "0.5g",
      "frequency": "每日三次"
    }
  ],
  "selected_candidate": null,
  "model_version": "yolo11n-v1",
  "rule_version": "rules-v1",
  "created_at": "2026-01-01T00:00:00Z"
}
```

### 确认候选

```
POST /api/v1/households/{household_id}/review-tasks/{task_id}/confirm
Content-Type: application/json
X-Idempotency-Key: uuid

{
  "selected_index": 0,
  "confirmation_note": "用户确认"
}
```

### 修正候选

```
POST /api/v1/households/{household_id}/review-tasks/{task_id}/correct
Content-Type: application/json
X-Idempotency-Key: uuid

{
  "manual_payload": {
    "drug_name": "B",
    "dosage": "0.5g",
    "frequency": "每日三次",
    "correction_note": "修正药品名称"
  }
}
```

`A` 和 `B` 仅为合成结构占位符，不代表真实药品或健康记录。

### 跳过

```
POST /api/v1/households/{household_id}/review-tasks/{task_id}/skip
```

## 测试与证据

- [ ] 覆盖匹配、冲突、未知、手工修正、重复点击、并发、撤权和事务故障
- [ ] 运行 API 契约、状态机、幂等、事件/outbox 和前端交互测试
- [ ] 人工演示从扫描到确认再到时间线的完整闭环
- [ ] 在 PR 中提供命令、环境、结果和可定位文件/测试链接
- [ ] 同步 Story、需求追踪矩阵及受影响事实源

## 回滚

关闭确认入口并保持任务为待复核；回退应用版本，保留已提交事件和审计，未完成事务不得部分落库。

## Ready 门禁

- [x] 已建立对应 docs/stories/HCT-xxx-*.md
- [ ] 已填写负责人、复核人、允许修改范围和预计完成时间
- [x] 已确认前置依赖 HCT-103、HCT-106、HCT-301 均已完成
- [ ] 从最新 GitHub master 创建单一任务分支
