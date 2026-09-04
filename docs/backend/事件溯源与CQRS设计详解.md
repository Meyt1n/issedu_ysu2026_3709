# 事件溯源与CQRS设计详解

> 本文档是家健镜系统事件溯源（Event Sourcing）与 CQRS 模式的完整设计说明，覆盖事件模型、事件存储、投影更新、快照机制、一致性保证、补偿机制。面向后端开发者和架构师，作为事件溯源实现的权威依据。

## 1. 为什么选择事件溯源

### 1.1 传统 CRUD 的问题

| 问题 | 说明 |
| --- | --- |
| 历史丢失 | 更新覆盖旧值，无法追溯变化 |
| 审计困难 | 需要额外的审计表，容易遗漏 |
| 调试困难 | 无法重现问题发生时的状态 |
| 冲突难处理 | 并发更新容易丢失 |
| 业务事件不明确 | 状态变化没有业务语义 |

### 1.2 事件溯源的优势

1. **完整历史**：所有变更都记录，可追溯任意时间点状态
2. **天然审计**：事件本身就是审计日志
3. **时间旅行**：可回放事件，重建任意时间点状态
4. **业务语义**：事件有明确的业务含义
5. **可调试**：通过事件流重现问题
6. **可扩展**：读模型可按需重建，不影响写模型

### 1.3 适用场景

- 需要完整审计的系统（医疗、金融）
- 业务流程复杂，需要追溯的系统
- 并发写入多，需要乐观锁的系统
- 需要时间维度分析的系统

## 2. 核心概念

### 2.1 事件（Event）

事件是过去发生的事实，不可变：

```python
class HealthEvent:
    event_id: UUID           # 唯一标识
    household_id: UUID       # 家庭
    member_id: UUID          # 成员
    sequence_no: int         # 成员内序号
    event_type: str          # 事件类型
    occurred_at: datetime    # 业务发生时间
    recorded_at: datetime    # 系统记录时间
    actor_user_id: UUID      # 操作者
    source_type: str         # 来源
    payload: dict            # 事件详情
    before_snapshot: dict    # 变更前快照
    after_snapshot: dict     # 变更后快照
    idempotency_key: str     # 幂等键
    correlation_id: UUID     # 关联 ID
    causation_id: UUID       # 因果 ID
    schema_version: int      # 事件 schema 版本
```

### 2.2 聚合根（Aggregate）

聚合根是一致性边界，所有事件通过聚合根产生：

```python
class MemberAggregate:
    def __init__(self, member_id: str):
        self.member_id = member_id
        self.medications: dict[str, Medication] = {}
        self.allergies: list[Allergy] = []
        self.conditions: list[Condition] = []
        self.latest_vitals: dict[str, VitalRecord] = {}
        self.active_plans: list[MedicationPlan] = []
        self.sequence_no = 0
        self.pending_events: list[HealthEvent] = []

    def add_medication(self, medication: Medication, actor: str) -> HealthEvent:
        # 业务规则校验
        if medication.medicine_id in self.medications:
            raise BusinessError("MEDICATION_EXISTS", "药品已存在")

        # 创建事件
        event = HealthEvent(
            event_type="medication_added",
            member_id=self.member_id,
            payload={"medication": medication.dict()},
            actor_user_id=actor,
            sequence_no=self.sequence_no + 1,
        )

        # 应用事件
        self._apply(event)
        self.pending_events.append(event)
        return event

    def _apply(self, event: HealthEvent):
        handler = getattr(self, f"_on_{event.event_type}", None)
        if handler:
            handler(event)
        self.sequence_no = event.sequence_no
```

### 2.3 事件类型

```python
EVENT_TYPES = {
    # 成员
    "member_created", "member_updated",
    # 药品
    "medication_added", "medication_updated", "medication_removed",
    # 过敏
    "allergy_added", "allergy_removed",
    # 疾病
    "condition_added", "condition_removed",
    # 体征
    "vital_recorded",
    # 计划
    "plan_created", "plan_updated", "plan_confirmed",
    "plan_deferred", "plan_skipped", "plan_missed",
    # 风险
    "risk_triggered", "risk_acknowledged",
    # 视觉
    "vision_submitted", "vision_confirmed", "vision_corrected",
    # 授权
    "authorization_created", "authorization_revoked",
    # 自定义
    "custom",
}
```

## 3. 事件存储

### 3.1 存储表

```sql
CREATE TABLE health_events (
    event_id UUID PRIMARY KEY,
    household_id UUID NOT NULL,
    member_id UUID NOT NULL,
    sequence_no INTEGER NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_user_id UUID NOT NULL,
    source_type VARCHAR(20) NOT NULL,
    payload JSONB NOT NULL,
    before_snapshot JSONB,
    after_snapshot JSONB,
    idempotency_key VARCHAR(100) UNIQUE,
    correlation_id UUID,
    causation_id UUID,
    supersedes_event_id UUID REFERENCES health_events(event_id),
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(member_id, sequence_no)
);
```

### 3.2 写入流程

```python
async def append_event(event: HealthEvent, db: AsyncSession) -> HealthEvent:
    # 1. 幂等检查
    if event.idempotency_key:
        existing = await db.execute(
            select(HealthEvent).where(
                HealthEvent.idempotency_key == event.idempotency_key
            )
        )
        if existing.scalar_one_or_none():
            raise IdempotencyConflictError(event.idempotency_key)

    # 2. 乐观锁检查（sequence_no 唯一约束）
    try:
        db.add(event)
        await db.flush()
    except IntegrityError as e:
        if "sequence_no" in str(e):
            raise VersionConflictError(
                "SEQUENCE_CONFLICT",
                "事件序号冲突，请重新加载聚合",
            )
        raise

    # 3. 写入 Outbox（同事务）
    outbox = OutboxMessage.from_event(event)
    db.add(outbox)

    return event
```

### 3.3 读取流程

```python
async def load_aggregate(member_id: str, db: AsyncSession) -> MemberAggregate:
    # 1. 尝试从快照恢复
    snapshot = await get_latest_snapshot(member_id, db)

    aggregate = MemberAggregate(member_id)
    start_sequence = 0

    if snapshot:
        aggregate.restore_from_snapshot(snapshot)
        start_sequence = snapshot.last_sequence_no

    # 2. 加载快照之后的事件
    result = await db.execute(
        select(HealthEvent)
        .where(
            HealthEvent.member_id == member_id,
            HealthEvent.sequence_no > start_sequence,
        )
        .order_by(HealthEvent.sequence_no)
    )

    # 3. 回放事件
    for event in result.scalars():
        aggregate.apply(event)

    return aggregate
```

## 4. CQRS 读写分离

### 4.1 写模型（Command）

写模型负责业务规则校验和事件持久化：

```python
class AddMedicationCommand:
    member_id: str
    medication: Medication
    idempotency_key: str

class AddMedicationHandler:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def handle(self, cmd: AddMedicationCommand) -> HealthEvent:
        # 1. 加载聚合
        aggregate = await load_aggregate(cmd.member_id, self.db)

        # 2. 执行业务操作（产生事件）
        event = aggregate.add_medication(cmd.medication, cmd.actor_id)

        # 3. 持久化事件
        await append_event(event, self.db)

        return event
```

### 4.2 读模型（Query）

读模型负责高效查询，预计算常用视图：

```python
class GetTodayTasksQuery:
    member_id: str
    date: date

class GetTodayTasksHandler:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def handle(self, query: GetTodayTasksQuery) -> TodayTasksResponse:
        # 直接查询读模型表，不回放事件
        result = await self.db.execute(
            select(DailyTask)
            .where(
                DailyTask.member_id == query.member_id,
                DailyTask.task_date == query.date,
            )
            .order_by(DailyTask.scheduled_time)
        )
        tasks = result.scalars().all()

        return TodayTasksResponse(
            date=query.date,
            tasks=[TaskView.from_model(t) for t in tasks],
            summary=calculate_summary(tasks),
        )
```

### 4.3 读模型更新

读模型通过 Outbox 事件异步更新：

```python
class OutboxWorker:
    async def process(self, message: OutboxMessage):
        event = parse_event(message.payload)

        # 根据事件类型更新对应的读模型
        handlers = {
            "medication_added": self._update_medications_view,
            "medication_removed": self._update_medications_view,
            "plan_confirmed": self._update_today_tasks_view,
            "plan_missed": self._update_today_tasks_view,
            "risk_triggered": self._update_risks_view,
            "risk_acknowledged": self._update_risks_view,
        }

        handler = handlers.get(event.event_type)
        if handler:
            await handler(event)

        await self.mark_dispatched(message.outbox_id)
```

## 5. 快照机制

### 5.1 为什么需要快照

事件回放成本随事件数量增长。快照定期保存聚合状态，回放时从快照开始：

```
事件1 → 事件2 → ... → 事件100 → [快照] → 事件101 → 事件102
                                         ↑
                                   从这里开始回放
```

### 5.2 快照表

```sql
CREATE TABLE member_projection_snapshots (
    snapshot_id UUID PRIMARY KEY,
    member_id UUID NOT NULL,
    last_event_id UUID NOT NULL,
    last_sequence_no INTEGER NOT NULL,
    projection_version VARCHAR(20) NOT NULL,
    projection_checksum VARCHAR(100) NOT NULL,
    state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5.3 快照策略

- 每 50 个事件创建一次快照
- 只保留最近 3 个快照
- 快照创建在后台异步进行
- 快照包含校验和，用于检测损坏

```python
async def create_snapshot_if_needed(member_id: str, db: AsyncSession):
    aggregate = await load_aggregate(member_id, db)

    # 检查是否需要快照
    last_snapshot = await get_latest_snapshot(member_id, db)
    last_snapshot_seq = last_snapshot.last_sequence_no if last_snapshot else 0

    if aggregate.sequence_no - last_snapshot_seq < 50:
        return

    # 创建快照
    snapshot = MemberProjectionSnapshot(
        member_id=member_id,
        last_event_id=aggregate.last_event_id,
        last_sequence_no=aggregate.sequence_no,
        projection_version="1.0",
        projection_checksum=aggregate.calculate_checksum(),
        state=aggregate.to_dict(),
    )
    db.add(snapshot)
    await db.commit()

    # 清理旧快照（只保留最近 3 个）
    await cleanup_old_snapshots(member_id, keep=3, db=db)
```

## 6. 一致性保证

### 6.1 最终一致性

写模型和读模型是最终一致的：

```
写操作 → 事件持久化 → Outbox → 读模型更新
                ↑ 同步          ↑ 异步
```

- 写操作成功后，事件已持久化（强一致）
- 读模型更新是异步的（最终一致，通常 <1 秒）
- 客户端可以通过轮询或 WebSocket 等待读模型更新

### 6.2 事务一致性

事件和 Outbox 在同一事务中写入：

```python
async with db.begin():  # 事务开始
    await db.execute(insert_event(event))    # 事件
    await db.execute(insert_outbox(event))   # Outbox
# 事务提交：两者同时成功或同时失败
```

### 6.3 幂等性

- 所有写操作支持幂等键
- 相同幂等键返回相同结果
- Outbox 分发也支持幂等（重复分发不产生重复效果）

### 6.4 乐观锁

通过 `sequence_no` 唯一约束实现乐观锁：

```python
try:
    await db.execute(insert_event(event))
    await db.commit()
except IntegrityError:
    await db.rollback()
    # 重新加载聚合，重试操作
    aggregate = await load_aggregate(member_id, db)
    event = aggregate.add_medication(...)
    await append_event(event, db)
```

## 7. 事件补偿

### 7.1 为什么需要补偿

错误事件不能删除（事件不可变），通过补偿事件修正：

```
事件A（错误） → 事件A'（补偿，supersedes A）
```

### 7.2 补偿实现

```python
async def compensate_event(
    event_id: str,
    reason: str,
    correction: dict,
    actor: str,
    db: AsyncSession,
) -> HealthEvent:
    original = await get_event(event_id, db)

    # 创建补偿事件
    compensation = HealthEvent(
        event_type=original.event_type,
        member_id=original.member_id,
        payload=correction,
        actor_user_id=actor,
        supersedes_event_id=original.event_id,
        correlation_id=original.correlation_id,
        causation_id=original.event_id,
        sequence_no=await get_next_sequence_no(original.member_id, db),
    )

    # 持久化补偿事件
    await append_event(compensation, db)

    return compensation
```

### 7.3 补偿回放

回放时，被 superseded 的事件不应用：

```python
def apply(self, event: HealthEvent):
    # 检查是否被补偿
    if event.supersedes_event_id:
        # 这是补偿事件，撤销原事件效果，应用新效果
        original = self._find_event(event.supersedes_event_id)
        self._reverse(original)
        self._apply_event(event)
    else:
        self._apply_event(event)
```

## 8. 事件版本化

### 8.1 Schema 版本

事件结构可能变化，通过 `schema_version` 管理：

```python
# v1: 简单药品
{"name": "氨氯地平", "dosage": "5mg"}

# v2: 增加成分
{"name": "氨氯地平", "dosage": "5mg", "ingredients": [{"name": "氨氯地平"}]}
```

### 8.2 版本升级

回放时自动升级旧版本事件：

```python
class MedicationAddedEventUpgrader:
    @staticmethod
    def upgrade_v1_to_v2(payload: dict) -> dict:
        if "ingredients" not in payload:
            payload["ingredients"] = [{"name": payload["name"]}]
        return payload

def upgrade_event(event: HealthEvent) -> HealthEvent:
    if event.schema_version == 1 and event.event_type == "medication_added":
        event.payload = MedicationAddedEventUpgrader.upgrade_v1_to_v2(event.payload)
        event.schema_version = 2
    return event
```

## 9. 事件回放与时间旅行

### 9.1 重建任意时间点状态

```python
async def get_state_at(member_id: str, point_in_time: datetime, db: AsyncSession):
    # 加载 point_in_time 之前的所有事件
    result = await db.execute(
        select(HealthEvent)
        .where(
            HealthEvent.member_id == member_id,
            HealthEvent.occurred_at <= point_in_time,
        )
        .order_by(HealthEvent.sequence_no)
    )

    aggregate = MemberAggregate(member_id)
    for event in result.scalars():
        aggregate.apply(event)

    return aggregate
```

### 9.2 事件重放

```python
async def replay_all_events(member_id: str, db: AsyncSession):
    # 清除所有读模型
    await clear_member_read_models(member_id, db)

    # 从头回放所有事件
    result = await db.execute(
        select(HealthEvent)
        .where(HealthEvent.member_id == member_id)
        .order_by(HealthEvent.sequence_no)
    )

    for event in result.scalars():
        await update_read_models(event, db)

    # 创建新快照
    await create_snapshot(member_id, db)
```

## 10. 性能考虑

### 10.1 事件表优化

- `(member_id, sequence_no)` 联合索引
- `(member_id, occurred_at DESC)` 时间索引
- `idempotency_key` 唯一索引
- 按时间分区（PostgreSQL，大表时）

### 10.2 快照优化

- 定期创建快照（每 50 事件）
- 快照压缩存储
- 快照异步创建，不影响写操作

### 10.3 读模型优化

- 读模型表针对查询优化索引
- 读模型可随时重建（删除后重新回放）
- 读模型更新批量处理

## 11. 事件溯源检查清单

- [ ] 所有状态变更通过事件
- [ ] 事件不可变（只追加，不修改删除）
- [ ] 事件有业务语义（不是 CRUD 事件）
- [ ] 事件包含 before/after 快照
- [ ] 幂等键唯一约束
- [ ] 乐观锁（sequence_no）
- [ ] 事件和 Outbox 同事务
- [ ] 快照机制正常工作
- [ ] 读模型最终一致
- [ ] 补偿事件可修正错误
- [ ] 事件版本化支持升级
- [ ] 可回放重建任意时间点状态

---

*事件溯源是家健镜的核心架构决策。完整的事件历史让健康数据可信、可追溯、可审计，这是医疗健康系统的基石。*
