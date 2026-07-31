# 数据库迁移

当前尚未选定数据库并建立迁移工具。本目录只表示未来迁移的计划位置。

数据库和迁移方案通过 ADR 后，数据库结构只能通过版本化迁移变更。若选择 Alembic，候选流程为：

```powershell
python -m alembic revision --autogenerate -m "说明"
python -m alembic upgrade head
```

以上命令在依赖和配置建立前不可执行。自动生成内容必须人工检查，尤其是删除列、数据回填、外键和降级逻辑；迁移 PR 必须包含空库、升级和回滚测试。
