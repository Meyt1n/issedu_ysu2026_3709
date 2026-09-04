# 后端API设计与RESTful规范

> 本文档是家健镜系统后端 API 设计与 RESTful 规范的完整设计说明，覆盖 API 设计原则、资源命名、请求响应、错误处理、版本管理。

## 1. 概述

### 1.1 设计原则

1. 资源导向
2. 统一规范
3. 可缓存
4. 分层系统
5. 按需代码

### 1.2 API 规范

| 规范 | 说明 |
| --- | --- |
| 协议 | HTTPS |
| 格式 | JSON |
| 编码 | UTF-8 |
| 认证 | Bearer Token |
| 版本 | URL 路径版本 |
| 分页 | offset/limit 或 cursor |

## 2. URL 设计

### 2.1 资源命名

```
# 正确
GET    /api/v1/users
GET    /api/v1/users/{id}
POST   /api/v1/users
PUT    /api/v1/users/{id}
DELETE /api/v1/users/{id}

# 子资源
GET    /api/v1/users/{id}/medicines
POST   /api/v1/users/{id}/medicines
GET    /api/v1/users/{id}/medicines/{medicineId}

# 错误
GET    /api/v1/getUser
GET    /api/v1/users/all
POST   /api/v1/users/create
DELETE /api/v1/users/delete/{id}
```

### 2.2 命名规范

```python
# 使用名词复数
/users, /medicines, /health-records

# 使用连字符分隔多词
/health-records, /medication-logs

# 避免动词
GET /users  # 不是 /getUsers
POST /users  # 不是 /createUser
```

## 3. HTTP 方法

### 3.1 方法语义

| 方法 | 说明 | 幂等 | 安全 |
| --- | --- | --- | --- |
| GET | 获取资源 | 是 | 是 |
| POST | 创建资源 | 否 | 否 |
| PUT | 全量更新 | 是 | 否 |
| PATCH | 部分更新 | 否 | 否 |
| DELETE | 删除资源 | 是 | 否 |
| HEAD | 获取头部 | 是 | 是 |
| OPTIONS | 获取选项 | 是 | 是 |

### 3.2 使用示例

```python
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/medicines", tags=["medicines"])

@router.get("", response_model=List[MedicineResponse])
async def list_medicines(
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_user),
):
    medicines = await medicine_service.get_user_medicines(current_user.id, page, size)
    return medicines

@router.get("/{medicine_id}", response_model=MedicineResponse)
async def get_medicine(
    medicine_id: str,
    current_user: User = Depends(get_current_user),
):
    medicine = await medicine_service.get_medicine(medicine_id)
    if not medicine or medicine.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="药品不存在")
    return medicine

@router.post("", response_model=MedicineResponse, status_code=201)
async def create_medicine(
    data: MedicineCreate,
    current_user: User = Depends(get_current_user),
):
    medicine = await medicine_service.create_medicine(current_user.id, data)
    return medicine

@router.put("/{medicine_id}", response_model=MedicineResponse)
async def update_medicine(
    medicine_id: str,
    data: MedicineUpdate,
    current_user: User = Depends(get_current_user),
):
    medicine = await medicine_service.update_medicine(medicine_id, current_user.id, data)
    return medicine

@router.delete("/{medicine_id}", status_code=204)
async def delete_medicine(
    medicine_id: str,
    current_user: User = Depends(get_current_user),
):
    await medicine_service.delete_medicine(medicine_id, current_user.id)
```

## 4. 请求与响应

### 4.1 请求格式

```json
POST /api/v1/medicines
Content-Type: application/json
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...

{
  "name": "阿莫西林",
  "dosage": "500mg",
  "frequency": "每日三次",
  "times": ["08:00", "14:00", "20:00"],
  "notes": "饭后服用"
}
```

### 4.2 响应格式

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "uuid",
    "name": "阿莫西林",
    "dosage": "500mg",
    "frequency": "每日三次",
    "times": ["08:00", "14:00", "20:00"],
    "created_at": "2026-09-04T10:00:00Z"
  },
  "timestamp": "2026-09-04T10:00:00Z",
  "request_id": "req-uuid"
}
```

### 4.3 分页响应

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [],
    "pagination": {
      "page": 1,
      "size": 20,
      "total": 100,
      "total_pages": 5,
      "has_next": true,
      "has_prev": false
    }
  }
}
```

### 4.4 列表响应

```python
class PaginatedResponse(BaseModel):
    items: List[Any]
    pagination: PaginationInfo

class PaginationInfo(BaseModel):
    page: int
    size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool

    @classmethod
    def create(cls, page: int, size: int, total: int):
        return cls(
            page=page,
            size=size,
            total=total,
            total_pages=(total + size - 1) // size,
            has_next=page * size < total,
            has_prev=page > 1,
        )
```

## 5. 错误处理

### 5.1 错误响应

```json
{
  "code": 40001,
  "message": "参数验证失败",
  "errors": [
    {
      "field": "email",
      "message": "邮箱格式不正确"
    },
    {
      "field": "password",
      "message": "密码长度至少8位"
    }
  ],
  "timestamp": "2026-09-04T10:00:00Z",
  "request_id": "req-uuid"
}
```

### 5.2 状态码

| 状态码 | 说明 | 使用场景 |
| --- | --- | --- |
| 200 | 成功 | GET/PUT/PATCH 成功 |
| 201 | 创建成功 | POST 创建成功 |
| 204 | 无内容 | DELETE 成功 |
| 400 | 请求错误 | 参数验证失败 |
| 401 | 未认证 | Token 缺失/无效 |
| 403 | 无权限 | 权限不足 |
| 404 | 不存在 | 资源不存在 |
| 409 | 冲突 | 资源已存在 |
| 422 | 语义错误 | 业务逻辑错误 |
| 429 | 限流 | 请求过于频繁 |
| 500 | 服务器错误 | 内部异常 |

### 5.3 业务错误码

```python
class ErrorCode:
    # 通用错误 10000-19999
    SUCCESS = 0
    UNKNOWN_ERROR = 10000
    INVALID_PARAMETER = 10001
    UNAUTHORIZED = 10002
    FORBIDDEN = 10003
    NOT_FOUND = 10004
    RATE_LIMITED = 10005

    # 用户错误 20000-29999
    USER_NOT_FOUND = 20001
    USER_ALREADY_EXISTS = 20002
    INVALID_CREDENTIALS = 20003
    TOKEN_EXPIRED = 20004

    # 药品错误 30000-39999
    MEDICINE_NOT_FOUND = 30001
    MEDICINE_ALREADY_EXISTS = 30002
    INVALID_DOSAGE = 30003

    # 健康错误 40000-49999
    HEALTH_RECORD_NOT_FOUND = 40001
    INVALID_HEALTH_VALUE = 40002
```

### 5.4 异常处理

```python
@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={
            "code": ErrorCode.INVALID_PARAMETER,
            "message": "参数验证失败",
            "errors": [
                {"field": e["loc"][-1], "message": e["msg"]}
                for e in exc.errors()
            ],
        },
    )

@app.exception_handler(AuthException)
async def auth_exception_handler(request, exc):
    return JSONResponse(
        status_code=401,
        content={
            "code": ErrorCode.UNAUTHORIZED,
            "message": str(exc),
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "code": ErrorCode.UNKNOWN_ERROR,
            "message": "服务器内部错误",
        },
    )
```

## 6. 版本管理

### 6.1 URL 版本

```
/api/v1/users
/api/v2/users
```

### 6.2 版本策略

```python
# v1 路由
router_v1 = APIRouter(prefix="/api/v1")

# v2 路由
router_v2 = APIRouter(prefix="/api/v2")

# 同时维护两个版本
app.include_router(router_v1)
app.include_router(router_v2)
```

### 6.3 弃用策略

```python
@router.get("/users/{id}")
async def get_user_v1(user_id: str):
    # 添加弃用头
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-12-31"
    response.headers["Link"] = '</api/v2/users/{id}>; rel="successor-version"'
    return user
```

## 7. 认证与授权

### 7.1 JWT 认证

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="无效的令牌")
        user = await user_service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的令牌")
```

### 7.2 权限控制

```python
def require_role(role: str):
    def decorator(user: User = Depends(get_current_user)):
        if user.role != role:
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return decorator

@router.delete("/users/{id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
):
    await user_service.delete_user(user_id)
```

## 8. API 文档

### 8.1 Swagger

```python
from fastapi import FastAPI

app = FastAPI(
    title="家健镜 API",
    description="家健镜系统后端 API 文档",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
```

## 9. API 设计检查清单

- [ ] 资源命名
- [ ] HTTP 方法
- [ ] 请求格式
- [ ] 响应格式
- [ ] 分页响应
- [ ] 错误响应
- [ ] 状态码
- [ ] 错误码
- [ ] 版本管理
- [ ] JWT 认证
- [ ] 权限控制
- [ ] API 文档

---

*规范的 API 设计是系统协作的基础。RESTful 原则、统一格式、清晰错误，让前后端协作高效顺畅。*
