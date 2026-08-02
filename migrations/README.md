# HomeCare Twin 数据库迁移

MySQL 8 是 HomeCare Twin 唯一事实主库，SQLAlchemy 2 与 Alembic 是计划中的访问和迁移基线。当前尚未创建工程配置，因此下列命令必须在依赖锁定并实际验证后才能作为可执行说明：

```powershell
python -m alembic revision --autogenerate -m "说明"
python -m alembic upgrade head
```

迁移顺序按[领域模型与数据库设计](../docs/vibe-coding/13-领域模型与数据库设计.md)：

1. 用户、家庭、成员、授权和审计；
2. `health_event`、outbox 和当前状态投影；
3. 药品主数据、批次、成员用药和计划；
4. 识别任务、证据、人工复核和困难样本；
5. 规则、风险和关系投影；
6. 文档、切片、工具调用和引用。

自动生成内容必须人工检查。每个迁移 PR 需验证空库升级、已有数据升级、索引/外键、事件和投影兼容、删除传播以及可执行的回滚或前滚修复。禁止手工修改共享数据库绕过迁移。
