# HomeCare Twin 业务 API

FastAPI 是统一业务入口，MySQL 8 是唯一事实主库。当前已建立一期 API 骨架：健康检查、家庭/成员、开发身份授权、手工确认事件、outbox 和成员状态投影；接口基线见[API 设计规范](../../docs/vibe-coding/06-API设计规范.md)，数据模型见[领域模型与数据库设计](../../docs/vibe-coding/13-领域模型与数据库设计.md)。

建议目录：

```text
app/
├─ routes/           HTTP、认证依赖和 Schema，不写 SQL
├─ schemas/          版本化请求/响应契约
├─ application/      用例、成员授权、事务和 AI 编排
├─ domain/           事件、计划、任务和告警预算规则
├─ persistence/      MySQL 仓储、outbox 和关系投影
├─ integrations/     CV、OCR、RAG、Ollama、天气适配器
├─ core/             配置、日志、错误和安全
└─ main.py           应用装配
```

核心约束：

- `health_event` 追加写，更正使用补偿事件；
- 只有人工确认或人工修正的识别结果可进入正式状态和风险计算；原预测、证据和修正原因必须保留；
- 风险等级由版本化规则生成，LLM 只调用工具和解释；
- 所有成员资源执行 RBAC + 成员/字段级 ABAC，结合动作、目的和期限；撤权立即生效；
- 家庭版网络出口默认拒绝，健康上下文不得作为云端模型回退发送；
- API 不提供买药、问诊、广告和佣金导流资源；
- 模型、向量库或天气离线时明确降级，不伪造结果。

开发环境启动：`uv run uvicorn app.main:app --app-dir src/api --reload`。当前身份使用 `X-Actor-Id` 开发请求头，仅用于一期本地骨架；生产环境必须替换为真实认证。实际接口状态以 OpenAPI、迁移、自动测试和需求追踪矩阵为准。
