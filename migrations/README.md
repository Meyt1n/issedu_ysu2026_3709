# 数据库迁移

数据库结构只通过 Alembic 变更。修改 `src/api/app/db/models.py` 后：

```powershell
$env:PYTHONPATH = "src/api"
python -m alembic revision --autogenerate -m "说明"
python -m alembic upgrade head
```

自动生成内容必须人工检查，尤其是删除列、数据回填、外键和降级逻辑。
