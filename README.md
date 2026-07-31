# 多模态智能医疗家庭助手

面向家庭健康管理实训的多模态 AI 系统，整合药物图像识别、医疗知识检索增强问答、健康数据管理和可观测后台。

> 本项目只提供健康信息与家庭照护辅助，不进行临床诊断、处方生成或自动用药决策。

## 当前阶段

仓库已结束 GitHub 操作练习，进入正式研发阶段。当前已交付 **一期：工程与身份权限基线**，
正在等待人工验收。

一期已完成：

1. 强类型配置、JSON 日志、请求 ID 和统一错误结构；
2. SQLAlchemy 异步数据层、Alembic 迁移和 PostgreSQL Compose；
3. 注册、登录、访问令牌、七天刷新令牌轮换与退出；
4. 家庭、成员角色、可撤销授权、资源所有权检查和脱敏审计；
5. 单元、集成、迁移和越权安全测试，以及 CI 质量门禁。

视觉模型、LLM、RAG、真实健康数据 CRUD 和管理后台不在一期范围，现有 Demo 会明确返回
“模型未接入”，不会生成虚假识别结果。详细边界见
[一期开发实施方案](docs/vibe-coding/16-一期开发实施方案.md)。

详细范围见 [需求规格说明书](docs/vibe-coding/01-需求规格说明书.md) 和
[需求追踪矩阵](docs/vibe-coding/12-需求追踪矩阵.md)。

## 核心能力

| 模块 | MVP 目标 | 安全边界 |
|---|---|---|
| 药物识别 | 返回候选药品、边界框、置信度和模型版本 | 低置信度拒识别，不给用药决定 |
| 医疗问答 | 多轮文本/图片问答，回答带来源 | 证据不足拒答，高风险症状转人工就医 |
| RAG 知识库 | PDF/DOCX 入库、权限检索、可定位引用 | 检索前鉴权，隔离私人知识域 |
| 健康数据 | 家庭成员、过敏史、体检指标和事件管理 | 最小采集、加密、审计、可导出删除 |
| 管理后台 | 用户、知识、模型、任务和服务状态 | RBAC，敏感操作二次确认 |

## 技术基线

- Web：Vue 3 + TypeScript + Vite
- API：Python 3.11 + FastAPI + Pydantic
- 数据：PostgreSQL、ChromaDB、MinIO、Redis
- AI：PyTorch、OpenCV、经评估的 YOLO、可替换 LLM 网关
- 测试：pytest、httpx、Playwright、安全回归集
- 部署：Docker Compose

完整选型与理由见 [技术方案](docs/vibe-coding/02-技术方案.md)。

## 仓库结构

```text
.
├─ src/
│  ├─ api/                 FastAPI 路由、应用服务、配置与数据层
│  ├─ web/                 Vue 用户端
│  ├─ ai/                  vision、rag、safety
│  └─ admin/               可选管理端
├─ tests/
│  ├─ unit/                单元测试
│  ├─ integration/         数据库与服务集成测试
│  ├─ e2e/                 端到端主链路
│  ├─ safety/              医疗安全与越权回归
│  └─ fixtures/            仅合成/脱敏测试数据
├─ docs/
│  ├─ vibe-coding/         需求、方案、约束和交付基线
│  └─ decisions/           架构决策记录
├─ .github/                CI、Issue 与 PR 模板
├─ migrations/             Alembic 数据库迁移
├─ compose.yaml            PostgreSQL 本地开发服务
├─ AGENTS.md               AI 编码工具强制约束
└─ CONTRIBUTING.md         正式研发协作规范
```

## 本地启动一期项目

前置条件：Python 3.11；使用 PostgreSQL 路径时还需要 Docker Desktop。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

打开 `.env`，至少替换 `APP_SECRET_KEY` 和 `POSTGRES_PASSWORD`，并确保
`DATABASE_URL` 中的密码一致。随后启动数据库和应用：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d postgres
.\scripts\start-demo.ps1
```

第一条命令生成的随机值用于 `APP_SECRET_KEY`，不要提交修改后的 `.env`。

`start-demo.ps1` 会先执行 `alembic upgrade head`，迁移成功后才启动 API。
不安装 Docker 的轻量练习方式见
[本地部署与 Demo 操作指南](docs/本地部署与Demo操作指南.md)。

启动后访问：

- 项目 Demo：<http://127.0.0.1:8000/>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- 数据库就绪检查：<http://127.0.0.1:8000/api/v1/ready>
- OpenAPI：<http://127.0.0.1:8000/docs>
- ReDoc：<http://127.0.0.1:8000/redoc>

运行质量检查：

```powershell
.\scripts\check-local.ps1
```

组员从克隆到验证的完整步骤见 [本地部署与 Demo 操作指南](docs/本地部署与Demo操作指南.md)。

## 开始开发

1. 阅读 [项目文档导航](docs/vibe-coding/00-文档导航.md) 和 [AGENTS.md](AGENTS.md)。
2. 从需求追踪矩阵或一期实施方案选择一个未完成条目，创建对应 Issue。
3. 从最新 `main` 创建 `feature/用户名-任务` 或 `fix/用户名-问题` 分支。
4. 小步实现并补测试，提交 Pull Request。
5. 满足 [完成定义](docs/vibe-coding/03-Vibe-Coding开发约束.md#6-完成定义) 后合并。

协作细节见 [CONTRIBUTING.md](CONTRIBUTING.md)。
