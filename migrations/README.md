# HomeCare Twin 数据库迁移

MySQL 8 是 HomeCare Twin 唯一事实主库，SQLAlchemy 2 与 Alembic 是当前访问和迁移基线。当前迁移已建立家庭、成员、授权审计、不可变健康事件、可恢复 outbox、状态投影和 checkpoint。

```powershell
uv run alembic upgrade head
uv run alembic current
uv run alembic revision --autogenerate -m "说明"
```

本地没有 MySQL 时可以用默认 SQLite 配置验证迁移；提交前仍必须在 MySQL 8.4 容器中执行一次空库升级。HCT-103 的 MySQL 触发器要求 `log_bin_trust_function_creators=1`，仓库 Compose 已固定该选项；其它部署必须由数据库管理员明确配置，不得让应用静默跳过不可变约束。

迁移顺序按[领域模型与数据库设计](../docs/vibe-coding/13-领域模型与数据库设计.md)：

1. 用户、家庭、成员、授权和审计；
2. `health_event`、outbox 和当前状态投影；
3. 药品主数据、批次、成员用药和计划；
4. 识别任务、证据、人工复核和困难样本；
5. 规则、风险和关系投影；
6. 文档、切片、工具调用和引用。

自动生成内容必须人工检查。每个迁移 PR 需验证空库升级、已有数据升级、索引/外键、事件和投影兼容、删除传播以及可执行的回滚或前滚修复。禁止手工修改共享数据库绕过迁移。

`0004_hct103_event_recovery` 在已有事件时拒绝 downgrade，因为删除序号、幂等、补偿和重放字段会破坏事实含义。回滚应用时先停止 outbox worker 并保留事件/outbox/checkpoint，数据库使用前滚修复；只有空事件库可降级结构。
