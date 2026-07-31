# 业务 API

FastAPI 是认证、授权、家庭成员、健康记录、审计和 AI 能力编排的唯一业务入口。

一期实际目录：

```text
app/
├─ routes/            HTTP 协议适配，不写 SQL
├─ schemas/           版本化请求/响应契约
├─ application/       用例、权限和事务编排
├─ db/                SQLAlchemy 模型与会话适配
├─ core/              配置、日志、错误、安全
├─ dependencies.py    FastAPI 鉴权与会话依赖
└─ main.py            应用装配，不承载业务规则
```

后续领域规则复杂后放入 `domain/`，外部模型和服务适配器放入 `integrations/`。路由不得直接
写 SQL、模型推理或医疗安全规则。公开接口先更新 OpenAPI 契约，再实现代码。

一期 API：

- `/api/v1/auth/*`：注册、登录、刷新和退出；
- `/api/v1/users/me`：当前用户；
- `/api/v1/families/*`：家庭与成员；
- `/api/v1/consent-grants/*`：创建、查询和撤销授权；
- `/api/v1/audit-events`：当前用户的脱敏审计；
- `/api/v1/health`、`/api/v1/ready`：存活和数据库就绪检查。
