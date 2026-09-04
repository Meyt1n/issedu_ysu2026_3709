# DevOps-多环境管理与配置管理

> 本文档是家健镜系统多环境管理与配置管理的完整设计说明，覆盖环境划分、配置策略、密钥管理、环境隔离、部署流程。

## 1. 概述

### 1.1 设计目标

1. 环境隔离
2. 配置统一管理
3. 密钥安全存储
4. 部署可追溯
5. 环境快速搭建

### 1.2 环境划分

| 环境 | 用途 | 数据 | 访问权限 |
| --- | --- | --- | --- |
| dev | 开发调试 | 模拟数据 | 开发团队 |
| test | 测试验证 | 测试数据 | 测试团队 |
| staging | 预发布 | 生产镜像 | 测试+运维 |
| prod | 生产环境 | 真实数据 | 运维团队 |
| dr | 灾备环境 | 生产同步 | 运维团队 |

## 2. 环境架构

### 2.1 环境拓扑

```
开发环境 (dev)
  ├── dev-db
  ├── dev-cache
  └── dev-app (1实例)

测试环境 (test)
  ├── test-db
  ├── test-cache
  └── test-app (2实例)

预发布环境 (staging)
  ├── staging-db (生产数据脱敏)
  ├── staging-cache
  └── staging-app (与生产同配置)

生产环境 (prod)
  ├── prod-db (主从)
  ├── prod-cache (集群)
  ├── prod-mq (集群)
  └── prod-app (多实例+负载均衡)

灾备环境 (dr)
  └── 与生产同构，数据实时同步
```

### 2.2 命名规范

```
# 资源命名
{project}-{env}-{service}-{instance}

# 示例
homecare-dev-backend-01
homecare-test-mysql-01
homecare-prod-redis-01

# 域名
dev-api.homecare.com
test-api.homecare.com
staging-api.homecare.com
api.homecare.com  # 生产
```

## 3. 配置管理

### 3.1 配置分层

```
配置优先级（从高到低）：
1. 环境变量
2. 命令行参数
3. 配置中心（Nacos/Apollo）
4. 环境配置文件（application-{env}.yml）
5. 默认配置文件（application.yml）
```

### 3.2 Spring Boot 配置

```yaml
# application.yml (公共配置)
spring:
  application:
    name: homecare-backend
  jackson:
    date-format: yyyy-MM-dd HH:mm:ss
    time-zone: Asia/Shanghai

server:
  port: 8080

management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics

---
# application-dev.yml
spring:
  datasource:
    url: jdbc:mysql://dev-mysql:3306/homecare_dev
    username: dev_user
    password: ${DB_PASSWORD}
  redis:
    host: dev-redis
    port: 6379

logging:
  level:
    com.homecare: DEBUG

---
# application-prod.yml
spring:
  datasource:
    url: jdbc:mysql://prod-mysql:3306/homecare_prod
    username: prod_user
    password: ${DB_PASSWORD}
    hikari:
      maximum-pool-size: 20
  redis:
    host: prod-redis
    port: 6379
    lettuce:
      pool:
        max-active: 20

logging:
  level:
    com.homecare: INFO
  file:
    name: /var/log/homecare/app.log
```

### 3.3 配置中心

```yaml
# Nacos 配置
spring:
  cloud:
    nacos:
      config:
        server-addr: nacos:8848
        namespace: ${ENV}
        group: HOMEHEALTH
        file-extension: yaml
        shared-configs:
          - data-id: common.yaml
            group: COMMON
            refresh: true
```

## 4. 密钥管理

### 4.1 Vault 集成

```python
import hvac

class SecretManager:
    def __init__(self, vault_url: str, token: str):
        self.client = hvac.Client(url=vault_url, token=token)

    def get_secret(self, path: str, key: str) -> str:
        secret = self.client.secrets.kv.v2.read_secret_version(path=path)
        return secret['data']['data'][key]

    def get_database_credentials(self, env: str) -> dict:
        return {
            'host': self.get_secret(f'{env}/database', 'host'),
            'port': self.get_secret(f'{env}/database', 'port'),
            'username': self.get_secret(f'{env}/database', 'username'),
            'password': self.get_secret(f'{env}/database', 'password'),
        }
```

### 4.2 Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: homecare-secrets
  namespace: homecare
type: Opaque
data:
  db-password: cGFzc3dvcmQ=
  api-key: YXBpa2V5
  jwt-secret: and0c2VjcmV0

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: homecare-backend
spec:
  template:
    spec:
      containers:
        - name: backend
          env:
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: homecare-secrets
                  key: db-password
            - name: API_KEY
              valueFrom:
                secretKeyRef:
                  name: homecare-secrets
                  key: api-key
```

### 4.3 密钥轮换

```python
class KeyRotation:
    def __init__(self, secret_manager: SecretManager):
        self.secret_manager = secret_manager

    def rotate_database_password(self, env: str):
        # 1. 生成新密码
        new_password = self._generate_password()

        # 2. 更新数据库密码
        self._update_db_password(env, new_password)

        # 3. 更新密钥存储
        self.secret_manager.client.secrets.kv.v2.create_or_update_secret(
            path=f'{env}/database',
            secret={'password': new_password},
        )

        # 4. 滚动重启应用
        self._restart_applications(env)

    def _generate_password(self, length: int = 32) -> str:
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits + string.punctuation
        return ''.join(secrets.choice(alphabet) for _ in range(length))
```

## 5. 环境隔离

### 5.1 网络隔离

```yaml
# NetworkPolicy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: env-isolation
  namespace: homecare-dev
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              env: dev
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              env: dev
```

### 5.2 数据库隔离

```sql
-- 每个环境独立数据库
CREATE DATABASE homecare_dev;
CREATE DATABASE homecare_test;
CREATE DATABASE homecare_staging;
CREATE DATABASE homecare_prod;

-- 独立用户
CREATE USER 'dev_user'@'%' IDENTIFIED BY '***';
GRANT ALL PRIVILEGES ON homecare_dev.* TO 'dev_user'@'%';

CREATE USER 'prod_user'@'%' IDENTIFIED BY '***';
GRANT ALL PRIVILEGES ON homecare_prod.* TO 'prod_user'@'%';
```

### 5.3 数据脱敏

```python
class DataMasker:
    @staticmethod
    def mask_phone(phone: str) -> str:
        return phone[:3] + '****' + phone[7:]

    @staticmethod
    def mask_email(email: str) -> str:
        local, domain = email.split('@')
        return local[0] + '***@' + domain

    @staticmethod
    def mask_id_card(id_card: str) -> str:
        return id_card[:6] + '********' + id_card[14:]

    @staticmethod
    def mask_name(name: str) -> str:
        if len(name) <= 1:
            return name
        return name[0] + '*' * (len(name) - 1)

    def mask_record(self, record: dict) -> dict:
        if 'phone' in record:
            record['phone'] = self.mask_phone(record['phone'])
        if 'email' in record:
            record['email'] = self.mask_email(record['email'])
        if 'id_card' in record:
            record['id_card'] = self.mask_id_card(record['id_card'])
        if 'name' in record:
            record['name'] = self.mask_name(record['name'])
        return record
```

## 6. 部署流程

### 6.1 CI/CD 流水线

```yaml
stages:
  - build
  - test
  - deploy-dev
  - deploy-test
  - deploy-staging
  - deploy-prod

deploy-dev:
  stage: deploy-dev
  script:
    - kubectl apply -f k8s/dev/
  environment:
    name: dev
  only:
    - develop

deploy-test:
  stage: deploy-test
  script:
    - kubectl apply -f k8s/test/
  environment:
    name: test
  only:
    - release/*

deploy-staging:
  stage: deploy-staging
  script:
    - kubectl apply -f k8s/staging/
  environment:
    name: staging
  when: manual

deploy-prod:
  stage: deploy-prod
  script:
    - kubectl apply -f k8s/prod/
  environment:
    name: production
  when: manual
  only:
    - master
```

### 6.2 蓝绿部署

```yaml
# Blue deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: homecare-backend-blue
spec:
  replicas: 3
  selector:
    matchLabels:
      app: homecare-backend
      version: blue
  template:
    metadata:
      labels:
        app: homecare-backend
        version: blue
    spec:
      containers:
        - name: backend
          image: homecare-backend:v1.0.0

# Service 切换
apiVersion: v1
kind: Service
metadata:
  name: homecare-backend
spec:
  selector:
    app: homecare-backend
    version: blue  # 切换为 green 即可完成部署
```

### 6.3 金丝雀发布

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: homecare-backend
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: homecare-backend
  service:
    port: 8080
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
      - name: request-success-rate
        threshold: 99
        interval: 1m
      - name: request-duration
        threshold: 500
        interval: 1m
```

## 7. 环境检查

### 7.1 健康检查

```python
class EnvironmentChecker:
    def __init__(self, env: str):
        self.env = env

    def check_all(self) -> dict:
        return {
            'database': self.check_database(),
            'redis': self.check_redis(),
            'mq': self.check_mq(),
            'storage': self.check_storage(),
            'external_apis': self.check_external_apis(),
        }

    def check_database(self) -> dict:
        try:
            connection = self._get_db_connection()
            version = connection.execute("SELECT VERSION()").fetchone()
            return {'status': 'healthy', 'version': version[0]}
        except Exception as e:
            return {'status': 'unhealthy', 'error': str(e)}
```

## 8. 多环境检查清单

- [ ] 环境划分
- [ ] 命名规范
- [ ] 配置分层
- [ ] 配置中心
- [ ] Vault 集成
- [ ] K8s Secrets
- [ ] 密钥轮换
- [ ] 网络隔离
- [ ] 数据库隔离
- [ ] 数据脱敏
- [ ] CI/CD 流水线
- [ ] 蓝绿部署

---

*规范的多环境管理是稳定交付的保障。环境隔离、配置统一、密钥安全，让每次发布都从容不迫。*
