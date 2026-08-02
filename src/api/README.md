# HomeCare Twin 业务 API

FastAPI 是统一业务入口，MySQL 8 是唯一事实主库。当前目录尚无 API 实现；接口基线见[API 设计规范](../../docs/vibe-coding/06-API设计规范.md)，数据模型见[领域模型与数据库设计](../../docs/vibe-coding/13-领域模型与数据库设计.md)。

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
- 只有人工确认的识别结果可进入正式状态和风险计算；
- 风险等级由版本化规则生成，LLM 只调用工具和解释；
- 所有成员资源执行 RBAC + 成员级 ABAC；撤权立即生效；
- 模型、向量库或天气离线时明确降级，不伪造结果。

实际接口状态以 OpenAPI、迁移、自动测试和需求追踪矩阵为准。
