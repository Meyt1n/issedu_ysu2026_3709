# 后端API版本管理与兼容性设计

> 本文档是家健镜系统 API 版本管理与兼容性的完整设计说明，覆盖版本策略、废弃流程、兼容性保障、客户端适配。

## 1. 版本管理概述

### 1.1 设计目标

1. 平滑演进：API 变更不破坏现有客户端
2. 明确版本：每个 API 有明确版本号
3. 可废弃：旧版本有明确的废弃时间表
4. 可迁移：提供版本迁移指南
5. 可监控：版本使用情况可监控

### 1.2 版本策略

采用 URL 路径版本号 + 语义化版本。

```
/api/v1/medicines
/api/v2/medicines
```

| 版本类型 | 说明 | URL 变化 |
| --- | --- | --- |
| 主版本 | 不兼容变更 | v1 -> v2 |
| 次版本 | 向后兼容新增 | 不变 |
| 修订版本 | Bug 修复 | 不变 |

## 2. 版本控制实现

### 2.1 路由版本化

```python
from fastapi import APIRouter

# v1 路由
v1_router = APIRouter(prefix="/api/v1")

@v1_router.get("/medicines")
async def list_medicines_v1():
    return {"data": []}

# v2 路由
v2_router = APIRouter(prefix="/api/v2")

@v2_router.get("/medicines")
async def list_medicines_v2():
    return {"data": [], "pagination": {"total": 0}}

app.include_router(v1_router)
app.include_router(v2_router)
```

### 2.2 响应格式版本化

```python
class APIResponse(BaseModel):
    version: str = "v1"
    data: Any
    meta: dict = {}

class V1Response(APIResponse):
    version: str = "v1"

class V2Response(APIResponse):
    version: str = "v2"
    pagination: Pagination
```

## 3. 兼容性保障

### 3.1 向后兼容规则

**允许的变更：**
- 新增可选字段
- 新增 API 端点
- 新增可选参数
- 优化响应时间
- 修复 Bug

**不允许的变更（需要新版本）：**
- 删除字段
- 修改字段类型
- 修改字段含义
- 删除 API 端点
- 修改必填参数
- 修改响应结构

### 3.2 字段新增兼容

```python
# v1 响应
class MedicineV1(BaseModel):
    id: str
    name: str
    dosage: str

# v2 响应（新增字段，向后兼容）
class MedicineV2(BaseModel):
    id: str
    name: str
    dosage: str
    frequency: Optional[str] = None  # 新增可选字段
    manufacturer: Optional[str] = None  # 新增可选字段
```

### 3.3 弃用标记

```python
@v1_router.get("/medicines/{id}")
async def get_medicine_v1(id: str):
    # 添加弃用 Header
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-12-31"
    response.headers["Link"] = '</api/v2/medicines/{id}>; rel="successor-version"'
    return medicine
```

## 4. 废弃流程

### 4.1 废弃阶段

| 阶段 | 时间 | 行为 |
| --- | --- | --- |
| 公告 | 废弃前 6 个月 | 文档标注废弃，通知开发者 |
| 警告 | 废弃前 3 个月 | API 返回 Deprecation Header |
| 日落 | 废弃日期 | API 返回 410 Gone |
| 移除 | 日落后 1 个月 | 完全移除代码 |

### 4.2 废弃通知

```python
class DeprecationMiddleware:
    def __init__(self, deprecated_endpoints):
        self.deprecated_endpoints = deprecated_endpoints

    async def __call__(self, request, call_next):
        response = await call_next(request)

        path = request.url.path
        if path in self.deprecated_endpoints:
            info = self.deprecated_endpoints[path]
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = info["sunset_date"]
            response.headers["Link"] = (
                f'<{info["successor"]}>; rel="successor-version"'
            )

        return response
```

## 5. 客户端适配

### 5.1 版本协商

```python
# 客户端请求时指定版本
headers = {
    "Accept": "application/json; version=v2",
    "X-API-Version": "v2",
}

# 服务端根据 Header 选择版本
class VersionNegotiation:
    def resolve_version(self, request):
        # 1. 从 URL 路径获取
        path = request.url.path
        if "/api/v1/" in path:
            return "v1"
        elif "/api/v2/" in path:
            return "v2"

        # 2. 从 Header 获取
        version = request.headers.get("X-API-Version")
        if version:
            return version

        # 3. 默认版本
        return "v1"
```

### 5.2 客户端降级

```dart
// Flutter 客户端版本适配
class ApiClient {
  Future<Medicine> getMedicine(String id) async {
    try {
      // 尝试 v2
      final response = await _get('/api/v2/medicines/$id');
      return Medicine.fromJsonV2(response.data);
    } on NotFoundException {
      // v2 不存在，降级到 v1
      final response = await _get('/api/v1/medicines/$id');
      return Medicine.fromJsonV1(response.data);
    }
  }
}
```

## 6. 版本监控

### 6.1 版本使用统计

```python
class VersionMetrics:
    def __init__(self):
        self.version_counts = defaultdict(int)

    def record_request(self, version):
        self.version_counts[version] += 1

    def get_report(self):
        total = sum(self.version_counts.values())
        return {
            version: {
                "count": count,
                "percentage": round(count / total * 100, 2),
            }
            for version, count in self.version_counts.items()
        }
```

## 7. API版本检查清单

- [ ] URL 路径版本化
- [ ] 语义化版本号
- [ ] 向后兼容规则
- [ ] 弃用标记 Header
- [ ] 废弃时间表
- [ ] 版本迁移文档
- [ ] 客户端版本协商
- [ ] 客户端降级策略
- [ ] 版本使用监控
- [ ] 废弃通知机制
- [ ] 多版本共存支持
- [ ] 版本测试覆盖

---

*API 版本管理是系统演进的保障。平滑、可控的版本演进，让系统持续进化而不破坏现有体验。*
