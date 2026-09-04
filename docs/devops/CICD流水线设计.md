# CI/CD流水线设计

> 本文档是家健镜系统 CI/CD 流水线的完整设计说明，覆盖持续集成、持续部署、环境管理、质量门禁、发布策略。面向 DevOps 工程师和后端开发者，作为 CI/CD 实现的权威依据。

## 1. CI/CD 概述

### 1.1 设计目标

1. **自动化**：代码提交后自动构建、测试、部署
2. **质量门禁**：测试不通过不允许合并
3. **快速反馈**：5 分钟内给出构建结果
4. **安全发布**：支持灰度、回滚
5. **环境一致**：开发、测试、生产环境配置一致

### 1.2 流水线阶段

```
代码提交
    ↓
┌─────────┐
│  代码检查  │ → lint、格式、安全扫描
└─────────┘
    ↓
┌─────────┐
│  构建     │ → 依赖安装、编译、打包
└─────────┘
    ↓
┌─────────┐
│  测试     │ → 单元测试、集成测试、覆盖率
└─────────┘
    ↓
┌─────────┐
│  制品管理  │ → Docker 镜像、构建产物
└─────────┘
    ↓
┌─────────┐
│  部署测试  │ → 自动部署到测试环境
└─────────┘
    ↓
┌─────────┐
│  人工审批  │ → 生产环境发布审批
└─────────┘
    ↓
┌─────────┐
│  灰度发布  │ → 逐步放量到生产
└─────────┘
```

## 2. 持续集成

### 2.1 GitHub Actions 配置

```yaml
name: CI

on:
  push:
    branches: [master, develop]
  pull_request:
    branches: [master, develop]

jobs:
  lint:
    name: Lint & Format
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install ruff black mypy
      - name: Run Ruff
        run: ruff check src/
      - name: Check Black format
        run: black --check src/
      - name: Run Mypy
        run: mypy src/

  test:
    name: Test
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run migrations
        run: alembic upgrade head
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/test_db
      - name: Run tests
        run: pytest --cov=src --cov-report=xml --cov-report=term
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml

  security:
    name: Security Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Bandit
        uses: PyCQA/bandit-action@v1
        with:
          args: -r src/ -ll
      - name: Run Safety
        run: |
          pip install safety
          safety check
```

### 2.2 质量门禁

```yaml
# 合并前必须通过的检查
name: Merge Gate

on:
  pull_request:
    branches: [master]

jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - name: Check lint
        run: ruff check src/
      - name: Check tests pass
        run: pytest
      - name: Check coverage
        run: |
          pytest --cov=src
          coverage report --fail-under=80
      - name: Check no secrets
        run: gitleaks detect
```

## 3. 持续部署

### 3.1 Docker 构建

```dockerfile
# 多阶段构建
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3.2 部署流水线

```yaml
name: CD

on:
  push:
    branches: [master]

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            homecare/backend:latest
            homecare/backend:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy-staging:
    needs: build-and-push
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - name: Deploy to staging
        run: |
          ssh user@staging-server "docker pull homecare/backend:${{ github.sha }} && docker-compose up -d"

  deploy-production:
    needs: deploy-staging
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Deploy to production (canary)
        run: |
          # 灰度发布：先部署 10% 流量
          kubectl set image deployment/homecare backend=homecare/backend:${{ github.sha }}
          kubectl rollout status deployment/homecare
```

## 4. 环境管理

### 4.1 环境矩阵

| 环境 | 用途 | 部署触发 | 数据 | 访问 |
| --- | --- | --- | --- | --- |
| dev | 开发调试 | 开发者手动 | Mock 数据 | 内网 |
| staging | 测试验证 | 自动（合并后） | 脱敏数据 | 内网 |
| canary | 灰度验证 | 自动（审批后） | 生产数据 10% | 生产 |
| production | 正式环境 | 自动（灰度后） | 生产数据 | 公网 |

### 4.2 配置管理

```yaml
# 环境配置通过环境变量注入
# .env.dev
DATABASE_URL=postgresql://user:pass@dev-db:5432/homecare
REDIS_URL=redis://dev-redis:6379
LOG_LEVEL=DEBUG

# .env.staging
DATABASE_URL=postgresql://user:pass@staging-db:5432/homecare
REDIS_URL=redis://staging-redis:6379
LOG_LEVEL=INFO

# .env.production
DATABASE_URL=postgresql://user:pass@prod-db:5432/homecare
REDIS_URL=redis://prod-redis:6379
LOG_LEVEL=WARNING
```

## 5. 发布策略

### 5.1 灰度发布

```yaml
# Kubernetes 滚动更新策略
apiVersion: apps/v1
kind: Deployment
metadata:
  name: homecare-backend
spec:
  replicas: 10
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 2        # 最多额外启动 2 个
      maxUnavailable: 0  # 不允许不可用
  minReadySeconds: 30   # 就绪后等待 30 秒
  progressDeadlineSeconds: 300
```

### 5.2 蓝绿部署

```bash
# 蓝绿部署脚本
#!/bin/bash
NEW_VERSION=$1

# 部署新版本（绿色环境）
docker-compose -f docker-compose.green.yml up -d

# 健康检查
for i in {1..30}; do
  if curl -f http://green:8000/health; then
    echo "Green healthy"
    break
  fi
  sleep 2
done

# 切换流量
nginx -s reload

# 验证
sleep 10
if curl -f http://prod/health; then
  echo "Switch successful"
  # 停止旧版本
  docker-compose -f docker-compose.blue.yml down
else
  echo "Switch failed, rolling back"
  nginx -s reload  # 切回蓝色
fi
```

### 5.3 回滚

```bash
# 回滚到上一个版本
kubectl rollout undo deployment/homecare-backend

# 回滚到指定版本
kubectl rollout undo deployment/homecare-backend --to-revision=3

# 数据库回滚
alembic downgrade -1
```

## 6. 制品管理

### 6.1 版本号规范

```
v{major}.{minor}.{patch}-{build}

示例：
v1.2.3-abc1234  # 开发版
v1.2.3          # 正式版
v1.2.3-rc1      # 候选版
```

### 6.2 Docker 镜像标签

- `latest`：最新稳定版
- `v1.2.3`：版本标签
- `abc1234`：commit SHA
- `staging`：测试环境版

## 7. 监控与告警

### 7.1 部署监控

- 部署成功率
- 部署时长
- 回滚次数
- 发布后错误率
- 发布后延迟变化

### 7.2 告警规则

| 指标 | 阈值 | 级别 |
| --- | --- | --- |
| 部署失败 | 1 次 | critical |
| 发布后错误率 >5% | 持续 5 分钟 | critical |
| 发布后 P95 延迟翻倍 | 持续 5 分钟 | warning |
| 回滚触发 | 1 次 | critical |

## 8. CI/CD检查清单

- [ ] 代码提交自动触发 CI
- [ ] Lint 检查通过
- [ ] 单元测试通过
- [ ] 覆盖率达标
- [ ] 安全扫描通过
- [ ] Docker 镜像构建成功
- [ ] 自动部署到测试环境
- [ ] 生产环境需要审批
- [ ] 支持灰度发布
- [ ] 支持快速回滚
- [ ] 环境配置隔离
- [ ] 密钥安全存储
- [ ] 部署有监控告警
- [ ] 制品版本可追溯

---

*CI/CD 是研发效率的引擎。自动化、高质量、安全的发布流程，让每次变更都快速可靠。*
