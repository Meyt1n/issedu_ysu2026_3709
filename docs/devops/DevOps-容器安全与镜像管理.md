# DevOps-容器安全与镜像管理

> 本文档是家健镜系统容器安全与镜像管理的完整指南，覆盖镜像构建、镜像扫描、运行时安全、密钥管理、合规审计。

## 1. 概述

### 1.1 安全目标

1. 镜像无已知漏洞
2. 容器最小权限运行
3. 运行时行为可监控
4. 密钥不泄露
5. 符合等保要求

### 1.2 安全层级

| 层级 | 安全措施 |
| --- | --- |
| 镜像层 | 基础镜像、依赖扫描、多阶段构建 |
| 运行时层 | 只读文件系统、非 root 用户、资源限制 |
| 网络层 | 网络策略、TLS 加密、API 认证 |
| 编排层 | RBAC、Pod 安全策略、审计日志 |

## 2. 镜像构建安全

### 2.1 多阶段构建

```dockerfile
# 构建阶段
FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o server .

# 运行阶段
FROM alpine:3.18
RUN apk --no-cache add ca-certificates tzdata
RUN adduser -D -u 10001 appuser
USER appuser
WORKDIR /app
COPY --from=builder /app/server .
EXPOSE 8080
ENTRYPOINT ["./server"]
```

### 2.2 基础镜像选择

```dockerfile
# 推荐：distroless 镜像
FROM gcr.io/distroless/static-debian12
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]

# 推荐：alpine 镜像
FROM alpine:3.18
RUN apk --no-cache add ca-certificates

# 不推荐：latest 标签
FROM ubuntu:latest  # 不稳定，可能引入漏洞
```

### 2.3 依赖固定版本

```dockerfile
# 固定基础镜像版本
FROM python:3.11-slim-bookworm

# 固定系统包版本
RUN apt-get update && apt-get install -y --no-install-recommends     curl=7.88.1-10+deb12u4     && rm -rf /var/lib/apt/lists/*

# 固定 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

### 2.4 .dockerignore

```
.git
.gitignore
*.md
Dockerfile
docker-compose.yml
node_modules
npm-debug.log
__pycache__
*.pyc
*.pyo
.env
*.env
.venv
venv
tests/
docs/
.pre-commit-config.yaml
```

## 3. 镜像扫描

### 3.1 Trivy 扫描

```bash
# 扫描镜像漏洞
trivy image --severity HIGH,CRITICAL homecare/backend:latest

# 扫描结果输出 JSON
trivy image --format json --output scan-result.json homecare/backend:latest

# 扫描配置文件
trivy config ./k8s/

# 扫描文件系统
trivy fs ./
```

### 3.2 CI 集成

```yaml
name: Container Security

on:
  push:
    branches: [master]
  pull_request:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build image
        run: docker build -t homecare/backend:${{ github.sha }} .

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: homecare/backend:${{ github.sha }}
          format: table
          exit-code: '1'
          ignore-unfixed: true
          severity: CRITICAL,HIGH
```

### 3.3 漏洞管理

```python
class VulnerabilityManager:
    def __init__(self, scan_results):
        self.scan_results = scan_results

    def get_critical_vulnerabilities(self) -> list:
        return [
            v for v in self.scan_results["vulnerabilities"]
            if v["Severity"] in ["CRITICAL", "HIGH"]
        ]

    def has_fixable_vulnerabilities(self) -> bool:
        return any(
            v.get("FixedVersion") for v in self.get_critical_vulnerabilities()
        )

    def generate_report(self) -> dict:
        critical = len([v for v in self.scan_results["vulnerabilities"] if v["Severity"] == "CRITICAL"])
        high = len([v for v in self.scan_results["vulnerabilities"] if v["Severity"] == "HIGH"])
        medium = len([v for v in self.scan_results["vulnerabilities"] if v["Severity"] == "MEDIUM"])

        return {
            "summary": {
                "critical": critical,
                "high": high,
                "medium": medium,
            },
            "pass": critical == 0 and high == 0,
        }
```

## 4. 运行时安全

### 4.1 非 root 用户

```dockerfile
# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -u 10001 appuser
USER appuser
```

### 4.2 只读文件系统

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-pod
spec:
  containers:
    - name: app
      image: homecare/backend:latest
      securityContext:
        readOnlyRootFilesystem: true
        runAsNonRoot: true
        runAsUser: 10001
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: cache
          mountPath: /cache
  volumes:
    - name: tmp
      emptyDir: {}
    - name: cache
      emptyDir: {}
```

### 4.3 资源限制

```yaml
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"
```

### 4.4 Pod 安全策略

```yaml
apiVersion: policy/v1beta1
kind: PodSecurityPolicy
metadata:
  name: restricted
spec:
  privileged: false
  allowPrivilegeEscalation: false
  requiredDropCapabilities:
    - ALL
  volumes:
    - configMap
    - emptyDir
    - projected
    - secret
    - downwardAPI
    - persistentVolumeClaim
  hostNetwork: false
  hostIPC: false
  hostPID: false
  runAsUser:
    rule: MustRunAsNonRoot
  seLinux:
    rule: RunAsAny
  supplementalGroups:
    rule: RunAsAny
  fsGroup:
    rule: RunAsAny
```

## 5. 密钥管理

### 5.1 不要在镜像中硬编码密钥

```dockerfile
# 错误：硬编码密钥
ENV API_KEY=sk-1234567890abcdef
ENV DB_PASSWORD=secret123

# 正确：运行时注入
ENV API_KEY=
ENV DB_PASSWORD=
```

### 5.2 Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: homecare-secrets
type: Opaque
data:
  db-password: c2VjcmV0MTIz  # base64 编码
  api-key: c2stMTIzNDU2Nzg5MGFiY2RlZg==
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: app
          envFrom:
            - secretRef:
                name: homecare-secrets
```

### 5.3 Vault 集成

```yaml
# 使用 Vault Agent 注入密钥
annotations:
  vault.hashicorp.com/agent-inject: "true"
  vault.hashicorp.com/role: "homecare"
  vault.hashicorp.com/agent-inject-secret-config: "secret/data/homecare/production"
  vault.hashicorp.com/agent-inject-template-config: |
    {{- with secret "secret/data/homecare/production" -}}
    DB_PASSWORD={{ .Data.data.db_password }}
    API_KEY={{ .Data.data.api_key }}
    {{- end }}
```

## 6. 网络安全

### 6.1 NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-network-policy
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: gateway
      ports:
        - protocol: TCP
          port: 8000
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: database
      ports:
        - protocol: TCP
          port: 5432
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
```

### 6.2 TLS 加密

```yaml
# 启用 TLS
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: homecare-ingress
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts:
        - api.homecare.com
      secretName: homecare-tls
  rules:
    - host: api.homecare.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: backend
                port:
                  number: 8000
```

## 7. 审计与监控

### 7.1 审计日志

```yaml
# Kubernetes 审计策略
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  - level: RequestResponse
    resources:
      - group: ""
        resources: ["secrets"]
  - level: Metadata
    resources:
      - group: ""
        resources: ["pods", "deployments", "services"]
```

### 7.2 运行时监控

```python
class RuntimeSecurityMonitor:
    def __init__(self):
        self.alerts = []

    def check_pod_security(self, pod_spec):
        issues = []

        # 检查是否以 root 运行
        if pod_spec.security_context.run_as_user == 0:
            issues.append("容器以 root 用户运行")

        # 检查特权模式
        if pod_spec.security_context.privileged:
            issues.append("容器运行在特权模式")

        # 检查只读文件系统
        if not pod_spec.security_context.read_only_root_filesystem:
            issues.append("根文件系统不是只读")

        return issues
```

## 8. 容器安全检查清单

- [ ] 多阶段构建
- [ ] 基础镜像安全
- [ ] 依赖版本固定
- [ ] .dockerignore
- [ ] 镜像漏洞扫描
- [ ] CI 安全检查
- [ ] 非 root 用户
- [ ] 只读文件系统
- [ ] 资源限制
- [ ] Pod 安全策略
- [ ] 密钥管理
- [ ] 网络策略

---

*容器安全是云原生的基石。从构建到运行，层层防护，让容器安全可靠。*
