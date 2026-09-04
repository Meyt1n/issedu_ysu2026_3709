# 后端GraphQL API设计

> 本文档是家健镜系统 GraphQL API 的完整设计说明，覆盖 Schema 设计、查询优化、权限控制、缓存策略。

## 1. GraphQL 概述

### 1.1 设计目标

1. 灵活查询：客户端按需获取数据
2. 减少请求：一次请求获取多个资源
3. 类型安全：强类型 Schema
4. 演进友好：无需版本号
5. 开发体验：自动文档和类型提示

### 1.2 REST vs GraphQL

| 特性 | REST | GraphQL |
| --- | --- | --- |
| 数据获取 | 多个端点 | 单一端点 |
| 过度获取 | 常见 | 按需获取 |
| 版本管理 | 需要版本号 | 字段级演进 |
| 缓存 | HTTP 缓存 | 需自定义 |
| 学习曲线 | 简单 | 中等 |

## 2. Schema 设计

### 2.1 类型定义

```graphql
type Query {
  medicine(id: ID!): Medicine
  medicines(filter: MedicineFilter, page: Int, size: Int): MedicineConnection!
  member(id: ID!): Member
  members(householdId: ID!): [Member!]!
  risks(memberId: ID!, status: RiskStatus): [Risk!]!
  healthRecords(memberId: ID!, type: VitalType, start: Date, end: Date): [HealthRecord!]!
  chatHistory(conversationId: ID!, page: Int, size: Int): MessageConnection!
}

type Mutation {
  createMedicine(input: CreateMedicineInput!): Medicine!
  updateMedicine(id: ID!, input: UpdateMedicineInput!): Medicine!
  deleteMedicine(id: ID!): Boolean!
  confirmRisk(id: ID!): Risk!
  sendMessage(conversationId: ID!, content: String!): Message!
}

type Subscription {
  riskCreated(memberId: ID!): Risk!
  messageReceived(conversationId: ID!): Message!
  medicineUpdated(memberId: ID!): Medicine!
}
```

### 2.2 实体类型

```graphql
type Medicine {
  id: ID!
  name: String!
  genericName: String
  specification: String
  manufacturer: String
  dosage: String!
  frequency: String!
  times: [String!]!
  ingredients: [Ingredient!]!
  expiryDate: Date
  stock: Int
  notes: String
  member: Member!
  medicationRecords(start: Date, end: Date): [MedicationRecord!]!
  createdAt: DateTime!
  updatedAt: DateTime!
}

type Member {
  id: ID!
  name: String!
  avatar: String
  role: MemberRole!
  birthDate: Date
  gender: Gender
  allergies: [String!]!
  medicalConditions: [String!]!
  medicines: [Medicine!]!
  healthRecords(type: VitalType, limit: Int): [HealthRecord!]!
  risks(status: RiskStatus): [Risk!]!
}

type Risk {
  id: ID!
  type: RiskType!
  level: RiskLevel!
  title: String!
  description: String!
  evidence: [RiskEvidence!]!
  recommendation: String
  status: RiskStatus!
  member: Member!
  createdAt: DateTime!
  confirmedAt: DateTime
}
```

### 2.3 输入类型

```graphql
input CreateMedicineInput {
  name: String!
  genericName: String
  specification: String
  manufacturer: String
  dosage: String!
  frequency: String!
  times: [String!]!
  expiryDate: Date
  stock: Int
  notes: String
}

input UpdateMedicineInput {
  name: String
  dosage: String
  frequency: String
  times: [String!]
  stock: Int
  notes: String
}

input MedicineFilter {
  name: String
  category: String
  expiryStatus: ExpiryStatus
}
```

### 2.4 分页连接

```graphql
type MedicineConnection {
  edges: [MedicineEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
}

type MedicineEdge {
  node: Medicine!
  cursor: String!
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}
```

## 3. 解析器实现

### 3.1 查询解析器

```python
class Query:
    def resolve_medicine(self, info, id):
        return medicine_service.get_by_id(id)

    def resolve_medicines(self, info, filter=None, page=1, size=20):
        return medicine_service.list(
            filter=filter,
            page=page,
            size=size,
        )

    def resolve_member(self, info, id):
        return member_service.get_by_id(id)
```

### 3.2 字段解析器（N+1 解决）

```python
from promise import Promise
from promise.dataloader import DataLoader

class MedicineLoader(DataLoader):
    def batch_load_fn(self, medicine_ids):
        medicines = medicine_service.get_by_ids(medicine_ids)
        return Promise.resolve([
            medicines.get(mid) for mid in medicine_ids
        ])

class MemberResolver:
    def resolve_medicines(self, member, info):
        return medicine_service.get_by_member(member.id)

    def resolve_health_records(self, member, info, type=None, limit=10):
        return health_record_service.get_by_member(
            member.id, type=type, limit=limit
        )
```

### 3.3 变更解析器

```python
class Mutation:
    def resolve_create_medicine(self, info, input):
        user = info.context["user"]
        return medicine_service.create(
            created_by=user.id,
            **input,
        )

    def resolve_update_medicine(self, info, id, input):
        user = info.context["user"]
        return medicine_service.update(
            id=id,
            updated_by=user.id,
            **input,
        )

    def resolve_delete_medicine(self, info, id):
        medicine_service.delete(id)
        return True
```

## 4. 权限控制

### 4.1 字段级权限

```python
def has_permission(user, resource, action):
    # 检查用户权限
    pass

class MedicineResolver:
    def resolve_medication_records(self, medicine, info, start=None, end=None):
        user = info.context["user"]
        if not has_permission(user, medicine.member_id, "read"):
            raise PermissionError("无权访问")
        return medication_record_service.get_by_medicine(
            medicine.id, start=start, end=end
        )
```

### 4.2 指令权限

```graphql
directive @auth(
  requires: Role = ADMIN,
) on OBJECT | FIELD_DEFINITION

type Medicine @auth(requires: USER) {
  id: ID!
  name: String!
  stock: Int @auth(requires: ADMIN)  # 只有管理员可见库存
}
```

## 5. 性能优化

### 5.1 DataLoader

```python
# 使用 DataLoader 解决 N+1 问题
loader = MedicineLoader()

# 批量加载
medicines = await loader.load_many([id1, id2, id3])
```

### 5.2 查询复杂度限制

```python
# 限制查询复杂度，防止恶意查询
class ComplexityLimit:
    def __init__(self, max_complexity=100):
        self.max_complexity = max_complexity

    def validate(self, document):
        complexity = self._calculate_complexity(document)
        if complexity > self.max_complexity:
            raise ValidationError(f"查询复杂度过高: {complexity}")
```

### 5.3 响应缓存

```python
# 基于查询哈希缓存
class QueryCache:
    def __init__(self, redis):
        self.redis = redis

    async def get_or_set(self, query_hash, resolver):
        cached = await self.redis.get(f"graphql:{query_hash}")
        if cached:
            return json.loads(cached)

        result = await resolver()
        await self.redis.setex(
            f"graphql:{query_hash}",
            300,
            json.dumps(result, default=str),
        )
        return result
```

## 6. 订阅实现

### 6.1 WebSocket 订阅

```python
class Subscription:
    async def resolve_risk_created(self, info, member_id):
        # 订阅 Redis 频道
        pubsub = info.context["redis"].pubsub()
        await pubsub.subscribe(f"risk:{member_id}")

        async for message in pubsub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])
```

## 7. GraphQL检查清单

- [ ] Schema 设计
- [ ] 查询解析器
- [ ] 变更解析器
- [ ] 订阅实现
- [ ] DataLoader
- [ ] 权限控制
- [ ] 复杂度限制
- [ ] 响应缓存
- [ ] 错误处理
- [ ] 类型安全
- [ ] API 文档
- [ ] 性能监控

---

*GraphQL 是 API 的未来。灵活、高效、类型安全的 API，让前端开发更加自由。*
