# DevOps运维手册

> 本文档是家健镜系统运维的完整手册，覆盖部署流程、日常运维、故障排查、应急响应、性能调优。

## 1. 运维概述

### 1.1 运维目标

1. 高可用：系统可用性 99.9%
2. 高性能：响应时间 < 500ms
3. 安全：数据安全和隐私保护
4. 可扩展：支持业务增长
5. 自动化：减少人工操作

### 1.2 运维职责

| 职责 | 说明 | 频率 |
| --- | --- | --- |
| 部署发布 | 新版本部署 | 按需 |
| 监控告警 | 系统状态监控 | 实时 |
| 备份恢复 | 数据备份和恢复 | 每日 |
| 性能调优 | 系统性能优化 | 持续 |
| 安全维护 | 安全补丁和审计 | 定期 |
| 故障处理 | 故障排查和修复 | 按需 |

## 2. 部署流程

### 2.1 部署前检查

```bash
#!/bin/bash
# 部署前检查清单

echo "=== 部署前检查 ==="

# 1. 检查代码
echo "1. 检查代码..."
git status
git log --oneline -5

# 2. 运行测试
echo "2. 运行测试..."
pytest --cov=src

# 3. 检查配置
echo "3. 检查配置..."
python -c "from config import settings; print(settings)"

# 4. 数据库迁移检查
echo "4. 检查数据库迁移..."
alembic current
alembic heads

# 5. 备份数据库
echo "5. 备份数据库..."
pg_dump homecare > backup_$(date +%Y%m%d).sql

echo "=== 检查完成，可以部署 ==="
```

### 2.2 部署步骤

```bash
#!/bin/bash
# 部署脚本

set -e

VERSION=$1
if [ -z "$VERSION" ]; then
  echo "Usage: $0 <version>"
  exit 1
fi

echo "=== 部署版本 $VERSION ==="

# 1. 拉取代码
git fetch origin
git checkout $VERSION

# 2. 安装依赖
pip install -r requirements.txt

# 3. 数据库迁移
alembic upgrade head

# 4. 构建 Docker 镜像
docker build -t homecare/backend:$VERSION .

# 5. 更新服务
docker-compose up -d

# 6. 健康检查
echo "等待服务启动..."
sleep 10
curl -f http://localhost:8000/health

# 7. 验证
echo "验证部署..."
curl http://localhost:8000/api/v1/version

echo "=== 部署完成 ==="
```

### 2.3 回滚流程

```bash
#!/bin/bash
# 回滚脚本

PREVIOUS_VERSION=$1

echo "=== 回滚到 $PREVIOUS_VERSION ==="

# 1. 回滚数据库
alembic downgrade -1

# 2. 切换镜像
docker-compose down
docker tag homecare/backend:$PREVIOUS_VERSION homecare/backend:latest
docker-compose up -d

# 3. 健康检查
sleep 10
curl -f http://localhost:8000/health

echo "=== 回滚完成 ==="
```

## 3. 日常运维

### 3.1 每日检查

```bash
#!/bin/bash
# 每日运维检查

echo "=== 每日检查 $(date) ==="

# 1. 系统状态
echo "1. 系统状态:"
uptime
free -h
df -h

# 2. Docker 状态
echo "2. Docker 状态:"
docker ps --format "table {{.Names}}	{{.Status}}	{{.Ports}}"

# 3. 服务健康
echo "3. 服务健康:"
curl -s http://localhost:8000/health | jq .

# 4. 数据库状态
echo "4. 数据库状态:"
docker exec postgres psql -U homecare -c "SELECT count(*) FROM medicines;"

# 5. 日志检查
echo "5. 最近错误日志:"
docker logs --since 24h backend 2>&1 | grep -i error | tail -20

# 6. 备份检查
echo "6. 备份状态:"
ls -lh /backup/*.sql | tail -5

echo "=== 检查完成 ==="
```

### 3.2 日志管理

```bash
# 查看实时日志
docker logs -f backend

# 查看最近 100 行
docker logs --tail 100 backend

# 查看特定时间段
docker logs --since 2026-09-04T10:00:00 --until 2026-09-04T12:00:00 backend

# 搜索错误
docker logs backend 2>&1 | grep -i error

# 日志轮转
# /etc/logrotate.d/docker
/var/lib/docker/containers/*/*.log {
    daily
    rotate 7
    compress
    missingok
    copytruncate
}
```

### 3.3 性能监控

```bash
# CPU 和内存
top
htop

# 磁盘 I/O
iostat -x 1

# 网络
iftop
nethogs

# Docker 资源使用
docker stats

# 数据库性能
docker exec postgres psql -U homecare -c "
  SELECT query, calls, total_time, mean_time
  FROM pg_stat_statements
  ORDER BY total_time DESC
  LIMIT 10;
"
```

## 4. 故障排查

### 4.1 常见故障

| 故障 | 可能原因 | 排查方法 |
| --- | --- | --- |
| 服务无法启动 | 配置错误、端口占用、依赖缺失 | 查看日志、检查配置 |
| 响应缓慢 | 数据库慢查询、资源不足、缓存失效 | 查看监控、分析慢查询 |
| 内存泄漏 | 代码 Bug、缓存未清理 | 内存分析、Heap Dump |
| 数据库连接满 | 连接池配置、慢查询 | 查看连接数、优化查询 |
| 磁盘满 | 日志、备份、临时文件 | 查看磁盘使用、清理 |
| 网络不通 | 防火墙、DNS、服务发现 | ping、telnet、nslookup |

### 4.2 排查流程

```bash
#!/bin/bash
# 故障排查脚本

echo "=== 故障排查 ==="

# 1. 检查服务状态
echo "1. 服务状态:"
systemctl status docker
docker ps

# 2. 检查资源
echo "2. 资源使用:"
free -h
df -h
uptime

# 3. 检查日志
echo "3. 最近错误:"
docker logs --tail 50 backend 2>&1 | grep -i error

# 4. 检查网络
echo "4. 网络连接:"
netstat -tlnp | grep 8000
curl -v http://localhost:8000/health

# 5. 检查数据库
echo "5. 数据库连接:"
docker exec postgres psql -U homecare -c "SELECT count(*) FROM pg_stat_activity;"

echo "=== 排查完成 ==="
```

### 4.3 应急响应

```
故障发生
    ↓
确认影响范围
    ↓
┌─────────────┐
│  P0 严重故障  │ → 立即通知团队，启动应急预案
└─────────────┘
    ↓
尝试快速恢复（重启/回滚）
    ↓
恢复成功？
    ├─ 是 → 记录故障，后续分析
    └─ 否 → 深入排查，寻求支援
    ↓
故障复盘
    ↓
改进措施
```

## 5. 备份恢复

### 5.1 备份策略

```bash
#!/bin/bash
# 每日备份脚本

BACKUP_DIR="/backup"
DATE=$(date +%Y%m%d_%H%M%S)

# 数据库备份
echo "备份数据库..."
docker exec postgres pg_dump -U homecare homecare | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# 文件备份
echo "备份文件..."
tar -czf "$BACKUP_DIR/files_$DATE.tar.gz" /data/files

# 上传到异地存储
echo "上传备份..."
aws s3 cp "$BACKUP_DIR/db_$DATE.sql.gz" s3://homecare-backups/
aws s3 cp "$BACKUP_DIR/files_$DATE.tar.gz" s3://homecare-backups/

# 清理 30 天前的备份
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete

echo "备份完成: $DATE"
```

### 5.2 恢复流程

```bash
#!/bin/bash
# 恢复脚本

BACKUP_FILE=$1

echo "从 $BACKUP_FILE 恢复..."

# 1. 停止服务
docker-compose stop backend

# 2. 恢复数据库
gunzip -c $BACKUP_FILE | docker exec -i postgres psql -U homecare homecare

# 3. 恢复文件
tar -xzf files_backup.tar.gz -C /data

# 4. 启动服务
docker-compose start backend

# 5. 验证
curl -f http://localhost:8000/health

echo "恢复完成"
```

## 6. 安全运维

### 6.1 安全检查

```bash
# 检查开放端口
netstat -tlnp

# 检查登录日志
last -20

# 检查失败登录
grep "Failed password" /var/log/auth.log | tail -10

# 检查系统更新
apt list --upgradable

# 检查 SSL 证书
openssl x509 -in /path/to/cert.pem -noout -dates
```

### 6.2 定期维护

- 每周：安全补丁更新
- 每月：系统更新
- 每季度：安全审计
- 每年：灾难恢复演练

## 7. 运维检查清单

- [ ] 部署流程
- [ ] 回滚流程
- [ ] 每日检查
- [ ] 日志管理
- [ ] 性能监控
- [ ] 故障排查
- [ ] 应急响应
- [ ] 备份策略
- [ ] 恢复流程
- [ ] 安全检查
- [ ] 定期维护
- [ ] 运维文档

---

*运维是系统稳定的保障。规范、高效的运维流程，让系统 7x24 小时稳定运行。*
