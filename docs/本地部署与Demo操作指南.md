# 本地部署与 Demo 操作指南

## 1. 部署目标

完成一次正式项目的本地部署闭环：

```text
克隆仓库 -> 创建虚拟环境 -> 配置数据库 -> 执行迁移
-> 运行检查 -> 启动一期项目 -> 验证页面和 API
```

一期包含注册登录、家庭、授权和审计 API，需要关系数据库，但不需要模型权重、GPU 或
真实患者数据。Demo 仍只使用报告参考图、合成输入和仓库内演示知识卡。

## 2. 环境要求

- Windows 10/11
- Git
- Python 3.11
- 浏览器：最新版 Chrome 或 Edge
- 推荐：Docker Desktop（PostgreSQL 路径）

检查：

```powershell
git --version
python --version
```

## 3. 克隆与进入仓库

```powershell
git clone https://github.com/Meyt1n/multimodal-medical-training.git
cd multimodal-medical-training
```

不要在其他项目目录或用户主目录直接执行后续命令。

## 4. 创建隔离环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

如果 PowerShell 阻止激活脚本，可在当前窗口执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

该设置只作用于当前 PowerShell 窗口。

## 5. 配置数据库

生成随机应用密钥：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把输出写入 `.env` 的 `APP_SECRET_KEY`。同时修改 `POSTGRES_PASSWORD`，并把相同密码写入
`DATABASE_URL`。

推荐使用 PostgreSQL：

```powershell
docker compose up -d postgres
docker compose ps
```

只做轻量本地练习、不安装 Docker 时，可以把 `.env` 的 `DATABASE_URL` 改为：

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./local-development.sqlite3
```

SQLite 仅用于个人开发和测试，不作为团队部署数据库。

## 6. 执行迁移

```powershell
$env:PYTHONPATH = "src/api"
python -m alembic upgrade head
```

迁移失败时不要手工建表，先检查 `.env` 和数据库状态。

## 7. 运行项目检查

```powershell
.\scripts\check-local.ps1
```

预期结果：

- Ruff 显示 `All checks passed!`
- mypy 显示 `Success: no issues found`
- pytest 全部通过且覆盖率不低于 80%

失败时保留完整错误，先确认 Python 版本、虚拟环境和依赖安装，不要删除测试或关闭检查。

## 8. 启动一期项目

```powershell
.\scripts\start-demo.ps1
```

脚本会再次幂等执行迁移，然后启动服务。保持终端窗口运行，浏览器打开：

- Demo：<http://127.0.0.1:8000/>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- 数据库就绪检查：<http://127.0.0.1:8000/api/v1/ready>
- OpenAPI：<http://127.0.0.1:8000/docs>
- ReDoc：<http://127.0.0.1:8000/redoc>

## 9. 验证清单

- [ ] 页面右下模块状态正常加载
- [ ] 选择本地图片后可以预览，页面明确说明图片未上传
- [ ] 运行药物接口演示后显示“未接入模型”，不生成虚假药名或置信度
- [ ] “用药核对”问题返回项目知识卡引用
- [ ] “高风险场景”触发 S3 紧急升级提示
- [ ] `/api/v1/health` 返回 `status: ok` 和版本号
- [ ] `/api/v1/ready` 返回 `status: ok`
- [ ] `/docs` 能看到 auth、users、families、consent、audit、health 和 demo 接口
- [ ] 可在 Swagger 注册合成用户并登录
- [ ] OpenAPI 响应头包含 `X-Request-ID`

## 10. 停止与清理

在运行 Demo 的终端按 `Ctrl+C` 停止服务。

使用 PostgreSQL 时可执行 `docker compose stop` 停止容器。不要随意执行
`docker compose down --volumes`，该命令会删除本地数据库卷。

`.venv`、`.env`、本地 SQLite、缓存和覆盖率文件都已被 `.gitignore` 忽略。

## 11. 常见问题

### 端口 8000 被占用

先停止原服务，或手动运行其他端口：

```powershell
$env:PYTHONPATH = "src/api"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8002
```

然后访问 <http://127.0.0.1:8002/>。

### 提示找不到 `app`

必须在仓库根目录启动，并使用 `scripts/start-demo.ps1`；手动启动时先设置：

```powershell
$env:PYTHONPATH = "src/api"
```

### 页面打开但状态加载失败

确认页面地址是 FastAPI 提供的 `http://127.0.0.1:8000/`，不要直接双击 `index.html`。

### 提示缺少或禁止示例 APP_SECRET_KEY

确认已经创建 `.env`，并用第 5 节命令生成的随机值替换示例值。不要把 `.env` 提交到 Git。

### 数据库连接失败

PostgreSQL 路径先执行 `docker compose ps`，确认状态为 healthy，并核对
`POSTGRES_PASSWORD` 与 `DATABASE_URL` 中密码一致。轻量 SQLite 路径确认 URL 使用
`sqlite+aiosqlite`。

## 12. 组员改进任务

每位组员可领取一个真实改进任务，例如：

- 增加成员移除与 owner 不可清空规则；
- 增加登录限流；
- 建立注册/登录前端页；
- 补 PostgreSQL 集成测试；
- 定义视觉或 RAG 适配器协议。

练习完成后按 [正式协作规范](../CONTRIBUTING.md) 提交 PR，不再创建签到文件或首次提交练习分支。
