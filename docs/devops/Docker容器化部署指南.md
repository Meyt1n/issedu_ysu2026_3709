# Docker容器化部署指南

> 本文档是家健镜系统 Docker 容器化部署的完整指南，覆盖镜像构建、容器编排、网络配置、存储管理、日志监控。面向运维人员和后端开发者，作为 Docker 部署的权威依据。

## 1. 容器化概述

### 1.1 设计目标

1. **环境一致**：开发、测试、生产环境一致
2. **快速部署**：镜像一键部署
3. **易于扩展**：水平扩展简单
4. **隔离性好**：服务间资源隔离
5. **可移植**：支持多种部署环境

### 1.2 服务架构

```
                    ┌─────────────┐
                    │   Nginx     │ ← 反向代理、负载均衡
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐
    │  Backend  │   │  Backend  │   │  Backend  │ ← 应用实例
    │  (x3)     │   │           │   │           │
    └─────┬─────┘   └───────────┘   └───────────┘
          │
    ┌─────┴──────────────────────────────┐
    │            数据层                    │
    │  ┌──────────┐  ┌────────┐  ┌────┐ │
    │  │PostgreSQL│  │ Redis  │  │MinIO│ │
    │  └──────────┘  └────────┘  └────┘ │
    └────────────────────────────────────┘
```

## 2. Dockerfile 最佳实践

### 2.1 多阶段构建

```dockerfile
# 构建阶段
FROM python:3.11-slim AS builder

WORKDIR /app

# 安装编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# 运行阶段
FROM python:3.11-slim AS runtime

WORKDIR /app

# 复制依赖
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# 复制应用代码
COPY src/ ./src/
COPY alembic.ini .
COPY migrations/ ./migrations/

# 创建非 root 用户
RUN useradd -m appuser
USER appuser

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 启动命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 2.2 镜像优化

| 优化项 | 说明 |
| --- | --- |
| 多阶段构建 | 减小最终镜像体积 |
| .dockerignore | 排除不必要文件 |
| 依赖缓存 | 利用 Docker 层缓存 |
| 非 root 用户 | 安全最佳实践 |
| slim 基础镜像 | 减小基础镜像体积 |
| 合并 RUN 指令 | 减少镜像层数 |

### 2.3 .dockerignore

```
.git
.gitignore
__pycache__
*.pyc
*.pyo
*.pyd
.Python
*.so
.venv
venv
env
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
htmlcov
coverage.xml
*.md
!README.md
docs/
tests/
scripts/
.preview/
.env
.env.*
!.env.example
*.log
*.tmp
```

## 3. Docker Compose

### 3.1 开发环境

```yaml
version: "3.8"

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.dev
    ports:
      - "8000:8000"
    volumes:
      - ./src:/app/src
      - ./migrations:/app/migrations
    environment:
      - DATABASE_URL=postgresql://homecare:secret@postgres:5432/homecare
      - REDIS_URL=redis://redis:6379/0
      - DEBUG=true
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    command: uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: homecare
      POSTGRES_USER: homecare
      POSTGRES_PASSWORD: secret
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U homecare"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    command: redis-server --appendonly yes

  worker:
    build:
      context: .
      dockerfile: Dockerfile.dev
    volumes:
      - ./src:/app/src
    environment:
      - DATABASE_URL=postgresql://homecare:secret@postgres:5432/homecare
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - backend
    command: python -m src.worker

volumes:
  pgdata:
  redisdata:
```

### 3.2 生产环境

```yaml
version: "3.8"

services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      - backend
    restart: always

  backend:
    image: homecare/backend:latest
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: "2"
          memory: 2G
        reservations:
          cpus: "1"
          memory: 1G
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - JWT_SECRET=${JWT_SECRET}
      - LOG_LEVEL=WARNING
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    restart: always
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: homecare
      POSTGRES_USER: homecare
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U homecare"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    restart: always

volumes:
  pgdata:
    driver: local
  redisdata:
    driver: local
```

## 4. 网络配置

### 4.1 网络隔离

```yaml
networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
  database:
    driver: bridge
    internal: true  # 内部网络，不访问外网

services:
  nginx:
    networks:
      - frontend
      - backend
  backend:
    networks:
      - backend
      - database
  postgres:
    networks:
      - database
```

### 4.2 Nginx 配置

```nginx
upstream backend {
    least_conn;
    server backend:8000 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name api.homecare.example.com;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }

    location /ws/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }

    location /health {
        proxy_pass http://backend/health;
        access_log off;
    }
}
```

## 5. 存储管理

### 5.1 数据卷

| 数据 | 存储方式 | 备份策略 |
| --- | --- | --- |
| PostgreSQL | 命名卷 | 每日全量 + WAL 归档 |
| Redis | 命名卷 | AOF 持久化 |
| 用户文件 | 绑定挂载 / MinIO | 异地备份 |
| 日志 | 绑定挂载 | 轮转 + 集中收集 |

### 5.2 数据库备份

```bash
#!/bin/bash
# 每日备份脚本
BACKUP_DIR="/backup/postgres"
DATE=$(date +%Y%m%d_%H%M%S)

docker exec postgres pg_dump -U homecare homecare | gzip > "$BACKUP_DIR/homecare_$DATE.sql.gz"

# 保留 30 天
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete

# 上传到对象存储
aws s3 cp "$BACKUP_DIR/homecare_$DATE.sql.gz" s3://homecare-backups/postgres/
```

## 6. 日志管理

### 6.1 日志驱动

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
    labels: "production,backend"
```

### 6.2 日志收集

```yaml
  fluentd:
    image: fluent/fluentd:v1.16
    volumes:
      - ./fluentd/conf:/fluentd/etc
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
    depends_on:
      - elasticsearch
```

## 7. 常用命令

```bash
# 构建镜像
docker build -t homecare/backend:latest .

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f backend

# 进入容器
docker-compose exec backend bash

# 重启服务
docker-compose restart backend

# 缩放服务
docker-compose up -d --scale backend=3

# 查看资源使用
docker stats

# 清理未使用资源
docker system prune -a

# 数据库迁移
docker-compose exec backend alembic upgrade head
```

## 8. Docker检查清单

- [ ] 多阶段构建
- [ ] .dockerignore 配置
- [ ] 非 root 用户运行
- [ ] 健康检查配置
- [ ] 环境变量注入
- [ ] 数据卷持久化
- [ ] 网络隔离
- [ ] 日志轮转
- [ ] 资源限制
- [ ] 重启策略
- [ ] 数据库备份
- [ ] 镜像安全扫描
- [ ] 镜像版本标签
- [ ] 密钥不硬编码

---

*Docker 是现代部署的基石。一致、隔离、可移植的容器化，让部署变得简单可靠。*
