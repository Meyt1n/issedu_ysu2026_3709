# 后端常见问题 FAQ

> 本文档收集家健镜系统后端开发和运维中的常见问题与解答，面向新加入的后端开发者和运维人员。

## 一、环境与配置

### Q1: 如何启动后端开发环境？

```bash
# 1. 克隆仓库
git clone https://github.com/Meyt1n/issedu_ysu2026_3709.git
cd issedu_ysu2026_3709

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入数据库、Redis 等配置

# 5. 启动依赖服务（Docker）
docker-compose up -d postgres redis

# 6. 运行数据库迁移
alembic upgrade head

# 7. 启动开发服务器
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Q2: 环境变量有哪些？

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| DATABASE_URL | PostgreSQL 连接串 | - |
| REDIS_URL | Redis 连接串 | - |
| JWT_SECRET | JWT 签名密钥 | - |
| JWT_ALGORITHM | JWT 算法 | HS256 |
| ACCESS_TOKEN_EXPIRE_MINUTES | Access Token 有效期 | 30 |
| REFRESH_TOKEN_EXPIRE_DAYS | Refresh Token 有效期 | 7 |
| MAX_UPLOAD_SIZE | 最大上传大小 | 50MB |
| STORAGE_PATH | 文件存储路径 | ./storage |
| LOG_LEVEL | 日志级别 | INFO |

### Q3: Windows 上安装依赖失败怎么办？

- 确保安装了 Visual C++ Build Tools
- 对于 `psycopg2`，可以改用 `psycopg2-binary`
- 对于 `pyzbar`，需要安装 Visual C++ Redistributable
- 对于 `faiss-cpu`，使用 `pip install faiss-cpu`

## 二、数据库

### Q4: 如何创建新的数据库迁移？

```bash
# 1. 修改 SQLAlchemy 模型
# 2. 自动生成迁移脚本
alembic revision --autogenerate -m "add xxx table"

# 3. 检查生成的迁移脚本（重要！自动生成可能不完整）
# 4. 执行迁移
alembic upgrade head
```

### Q5: 迁移冲突了怎么办？

```bash
# 查看当前分支和主分支的迁移
alembic heads

# 如果有多个 head，需要合并
alembic merge -m "merge branches" <head1> <head2>

# 然后重新执行
alembic upgrade head
```

### Q6: 如何回滚迁移？

```bash
# 回滚一个版本
alembic downgrade -1

# 回滚到指定版本
alembic downgrade <revision_id>

# 回滚所有
alembic downgrade base
```

### Q7: 如何查看数据库当前版本？

```bash
alembic current
alembic history --verbose
```

### Q8: 如何执行原始 SQL？

```python
from sqlalchemy import text

async def execute_raw_sql(db: AsyncSession):
    result = await db.execute(text("SELECT * FROM users WHERE id = :id"), {"id": 1})
    return result.fetchall()
```

## 三、API 开发

### Q9: 如何添加新的 API 端点？

```python
# 1. 在 src/api/v1/ 下创建或修改路由文件
from fastapi import APIRouter, Depends
from src.dependencies import get_db

router = APIRouter(prefix="/xxx", tags=["xxx"])

@router.get("/{id}")
async def get_xxx(id: str, db: AsyncSession = Depends(get_db)):
    # 业务逻辑
    return {"id": id}

# 2. 在 src/api/v1/__init__.py 中注册路由
from .xxx import router as xxx_router
api_router.include_router(xxx_router)
```

### Q10: 如何添加权限校验？

```python
from src.dependencies import get_current_user, require_household_member

@router.post("/households/{household_id}/xxx")
async def create_xxx(
    household_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 校验家庭成员身份
    await require_household_member(current_user.user_id, household_id, db)
    # 业务逻辑
```

### Q11: 如何统一错误处理？

```python
# 自定义异常
class BusinessError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code

# 全局异常处理器
@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
```

### Q12: 如何添加请求参数校验？

```python
from pydantic import BaseModel, Field, field_validator

class CreateMedicineRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    dosage: str = Field(..., max_length=100)
    frequency: str = Field(..., max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("药品名称不能为空")
        return v.strip()
```

### Q13: 如何实现分页？

```python
class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int

@router.get("/xxx", response_model=PaginatedResponse)
async def list_xxx(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Xxx).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    total_result = await db.execute(select(func.count()).select_from(Xxx))
    total = total_result.scalar()

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )
```

## 四、认证与授权

### Q14: JWT Token 的结构是什么？

```python
# Access Token payload
{
    "sub": "user_id",
    "type": "access",
    "exp": 1693800000,  # 30 分钟后过期
    "iat": 1693798200
}

# Refresh Token payload
{
    "sub": "user_id",
    "type": "refresh",
    "exp": 1694403000,  # 7 天后过期
    "iat": 1693798200
}
```

### Q15: 如何刷新 Token？

```python
@router.post("/auth/refresh")
async def refresh_token(refresh_request: RefreshTokenRequest):
    try:
        payload = verify_jwt(refresh_request.refresh_token)
        if payload["type"] != "refresh":
            raise BusinessError("INVALID_TOKEN", "无效的刷新令牌")

        user_id = payload["sub"]
        new_access_token = create_access_token(user_id)
        return {"access_token": new_access_token, "token_type": "bearer"}
    except ExpiredSignatureError:
        raise BusinessError("TOKEN_EXPIRED", "刷新令牌已过期，请重新登录")
```

### Q16: 如何实现角色权限？

```python
def require_role(role: str):
    async def checker(current_user: User = Depends(get_current_user)):
        if current_user.role != role:
            raise PermissionError("INSUFFICIENT_PERMISSION", f"需要 {role} 角色")
        return current_user
    return checker

# 使用
@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
):
    ...
```

## 五、事件溯源

### Q17: 如何创建新的事件类型？

1. 在 `src/domain/events.py` 中定义事件类
2. 在 `src/infrastructure/persistence/models.py` 中添加事件表
3. 创建 Alembic 迁移
4. 在事件服务中添加创建方法
5. 添加事件投影（更新读模型）

### Q18: 事件可以修改或删除吗？

**不可以**。事件是不可变的，一旦写入就不能修改或删除。如果需要修正，应该创建一个新的补偿事件。

```python
# 错误：不能这样做
# await db.execute(delete(HealthEvent).where(HealthEvent.event_id == xxx))

# 正确：创建补偿事件
await create_event(
    event_type="medication_removed",
    member_id=member_id,
    payload={"medication_id": medication_id, "reason": "输入错误"},
    actor_user_id=user_id,
    db=db,
)
```

### Q19: 如何重放事件？

```python
async def replay_events(member_id: str, db: AsyncSession):
    result = await db.execute(
        select(HealthEvent)
        .where(HealthEvent.member_id == member_id)
        .order_by(HealthEvent.occurred_at, HealthEvent.sequence)
    )
    events = result.scalars().all()

    state = MemberState()
    for event in events:
        state.apply(event)

    return state
```

## 六、文件处理

### Q20: 支持哪些文件格式？

| 类型 | 格式 | 大小限制 |
| --- | --- | --- |
| 图片 | JPG, PNG, WebP | 10MB |
| 视频 | MP4, MOV | 100MB |
| 文档 | PDF, Markdown | 20MB |

### Q21: 如何上传文件？

```python
from fastapi import UploadFile, File

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    # 校验文件类型和大小
    validate_file(file)

    # 保存文件
    file_id = await save_file(file, current_user.user_id)

    return {"file_id": file_id, "filename": file.filename}
```

### Q22: 文件存储在哪里？

- 开发环境：本地文件系统 `./storage/`
- 生产环境：可配置 S3/MinIO
- 文件元数据存储在数据库 `file_references` 表

## 七、测试

### Q23: 如何运行测试？

```bash
# 运行所有测试
pytest

# 运行指定文件
pytest tests/test_medicine.py

# 运行指定测试函数
pytest tests/test_medicine.py::test_create_medicine

# 显示详细输出
pytest -v

# 生成覆盖率报告
pytest --cov=src --cov-report=html
```

### Q24: 如何编写单元测试？

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_create_medicine():
    db = AsyncMock()
    service = MedicineService(db)

    result = await service.create_medicine(
        member_id="test-member",
        name="阿莫西林",
        dosage="0.5g",
        frequency="每日三次",
        actor_user_id="test-user",
    )

    assert result.name == "阿莫西林"
    db.add.assert_called_once()
    db.commit.assert_called_once()
```

### Q25: 如何编写集成测试？

```python
@pytest.mark.asyncio
async def test_create_medicine_api(client, db_session):
    # 准备测试数据
    user = await create_test_user(db_session)
    household = await create_test_household(db_session, user)
    member = await create_test_member(db_session, household)

    token = create_test_token(user.user_id)

    # 发送请求
    response = await client.post(
        f"/api/v1/members/{member.member_id}/medications",
        json={"name": "阿莫西林", "dosage": "0.5g", "frequency": "每日三次"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "阿莫西林"
```

## 八、部署

### Q26: 如何构建 Docker 镜像？

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t homecare-backend:latest .
docker run -d -p 8000:8000 --env-file .env homecare-backend:latest
```

### Q27: 如何使用 Docker Compose 启动全部服务？

```yaml
version: "3.8"
services:
  backend:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: homecare
      POSTGRES_USER: homecare
      POSTGRES_PASSWORD: secret
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7
    volumes:
      - redisdata:/data

volumes:
  pgdata:
  redisdata:
```

### Q28: 如何查看应用日志？

```bash
# Docker
docker logs -f homecare-backend

# systemd
journalctl -u homecare-backend -f

# 日志文件
tail -f /var/log/homecare/backend.log
```

## 九、性能

### Q29: 如何优化慢查询？

1. 使用 `EXPLAIN ANALYZE` 分析查询计划
2. 添加合适的索引
3. 避免 SELECT *，只查需要的字段
4. 使用分页限制返回数量
5. 对频繁查询的结果加缓存

### Q30: 如何添加缓存？

```python
from src.infrastructure.cache import get_redis

async def get_member_profile(member_id: str, db: AsyncSession):
    redis = await get_redis()
    cache_key = f"member:profile:{member_id}"

    # 尝试从缓存获取
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # 从数据库查询
    member = await db.get(Member, member_id)

    # 写入缓存（5 分钟过期）
    await redis.setex(cache_key, 300, member.model_dump_json())

    return member
```

### Q31: 如何处理并发？

- 数据库操作使用异步（async/await）
- 耗时操作移到后台 Worker
- 使用 Redis 分布式锁防止并发冲突
- 数据库乐观锁（version 字段）

## 十、其他

### Q32: 代码规范是什么？

- Python 3.11+
- 使用 `black` 格式化代码
- 使用 `isort` 排序导入
- 使用 `mypy` 做类型检查
- 使用 `ruff` 做 lint
- 遵循 PEP 8

### Q33: 如何提交代码？

```bash
# 1. 创建功能分支
git checkout -b feature/xxx

# 2. 编写代码和测试
# 3. 运行检查
black src/
isort src/
ruff check src/
pytest

# 4. 提交
git add .
git commit -m "feat: add xxx feature"

# 5. 推送并创建 PR
git push origin feature/xxx
```

### Q34: 遇到问题去哪里找帮助？

1. 先查本文档和其他技术文档
2. 查看 `docs/vibe-coding/` 下的开发指南
3. 搜索 GitHub Issues
4. 在团队群中提问

---

*FAQ 是新人入门的捷径，也是老人避坑的手册。持续更新，让问题不再重复。*
